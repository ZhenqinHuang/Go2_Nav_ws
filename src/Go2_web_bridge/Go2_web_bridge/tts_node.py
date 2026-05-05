#!/usr/bin/env python3
"""
TTS 语音播报节点（Edge TTS 版）

订阅 /tts_text (std_msgs/String)，调用微软 Edge TTS 在线合成音频，
通过 mpg123 直接输出到 ALSA 设备（默认 plughw:2,0 = USB 音频）。

默认声音: zh-CN-XiaoxiaoNeural（晓晓，自然女声）
其他可选: zh-CN-XiaoyiNeural / zh-CN-XiaohanNeural / zh-CN-XiaomoNeural
"""

import asyncio
import os
import queue
import subprocess
import tempfile
import threading

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

try:
    import edge_tts
except ImportError:
    raise RuntimeError('请安装 edge-tts: pip3 install edge-tts')

_G  = '\033[0;32m'
_Y  = '\033[1;33m'
_C  = '\033[0;36m'
_NC = '\033[0m'


def cprint(color: str, msg: str):
    print(f'{color}{msg}{_NC}', flush=True)


class TtsNode(Node):
    def __init__(self):
        super().__init__('tts_node')

        self.declare_parameter('queue_size',      5)
        self.declare_parameter('tts_topic',       '/tts_text')
        self.declare_parameter('alsa_device',     'plughw:GoUSBAudio,0')
        self.declare_parameter('alsa_card_index', '0')
        self.declare_parameter('voice',           'zh-CN-XiaoxiaoNeural')
        self.declare_parameter('rate',            '+0%')
        self.declare_parameter('volume',          '+0%')

        q_size                = self.get_parameter('queue_size').value
        tts_topic             = self.get_parameter('tts_topic').value
        self._device          = self.get_parameter('alsa_device').value
        self._alsa_card_index = self.get_parameter('alsa_card_index').value
        self._voice           = self.get_parameter('voice').value
        self._rate            = self.get_parameter('rate').value
        self._volume          = self.get_parameter('volume').value

        # 启动时将 USB 音频音量拉满，防止重启后静音
        # 开机自启动时 USB 设备可能尚未就绪，重试最多 30 次（每次等 1s）
        threading.Thread(target=self._init_volume, daemon=True).start()

        self.create_subscription(String, tts_topic, self._tts_cb, 10)

        self._queue: queue.Queue = queue.Queue(maxsize=q_size)
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

        cprint(_C, f'[TTS] 节点启动  话题={tts_topic}  声音={self._voice}  设备={self._device}')

    def _init_volume(self):
        """开机时 USB 音频可能尚未就绪，循环重试直到设置成功。"""
        import time
        for i in range(30):
            r = subprocess.run(
                ['amixer', '-c', self._alsa_card_index, 'sset', 'PCM Playback Volume', '100%'],
                capture_output=True,
            )
            if r.returncode == 0:
                cprint(_C, f'[TTS] 音量已拉满（第 {i+1} 次尝试）')
                return
            time.sleep(1)
        cprint(_Y, '[TTS] 警告：音量初始化失败，USB 音频设备可能未就绪')

    def _tts_cb(self, msg: String):
        text = msg.data.strip()
        if not text:
            self._clear_queue()
            return
        cprint(_G, f'[TTS] 收到文本: {text}')
        try:
            self._queue.put_nowait(text)
        except queue.Full:
            cprint(_Y, '[TTS] 队列已满，丢弃最旧消息')
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            self._queue.put_nowait(text)

    def _clear_queue(self):
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        cprint(_Y, '[TTS] 队列已清空')

    def _speak(self, text: str):
        cprint(_G, f'[TTS] 播报: {text}')

        async def _synthesize(tmpfile: str):
            communicate = edge_tts.Communicate(
                text, self._voice,
                rate=self._rate,
                volume=self._volume,
            )
            await communicate.save(tmpfile)

        tmpfile = tempfile.mktemp(suffix='.mp3')
        try:
            asyncio.run(_synthesize(tmpfile))
            # 播放前确保音量最大（防止重启后音量重置）
            subprocess.run(
                ['amixer', '-c', self._alsa_card_index, 'sset', 'PCM Playback Volume', '100%'],
                capture_output=True,
            )
            result = subprocess.run(
                ['mpg123', '-a', self._device, '-q', tmpfile],
                env={**os.environ, 'AUDIODEV': self._device},
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                cprint(_Y, f'[TTS] mpg123 失败(code={result.returncode}): {result.stderr.strip()}')
        except Exception as e:
            cprint(_Y, f'[TTS] 播报失败: {e}')
        finally:
            if os.path.exists(tmpfile):
                os.unlink(tmpfile)

    def _worker_loop(self):
        while rclpy.ok():
            try:
                text = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            self._speak(text)


def main(args=None):
    rclpy.init(args=args)
    node = TtsNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
