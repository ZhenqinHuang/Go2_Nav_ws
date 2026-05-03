#!/usr/bin/env python3
"""
TTS 语音播报节点

订阅 /tts_text (std_msgs/String)，用 espeak-ng 生成 PCM 音频，
通过 unitree_go/msg/AudioData 发布到 /audiosender，
由机器狗本体的音频服务驱动扬声器播报。

要求: espeak-ng 已安装，音频格式固定为 16000Hz / 单声道 / 16bit PCM
发布空字符串 "" 到 /tts_text 可立即中断当前播报并清空队列。
"""

import array
import subprocess
import struct
import threading
import time
import queue

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

_G  = '\033[0;32m'
_Y  = '\033[1;33m'
_C  = '\033[0;36m'
_NC = '\033[0m'

SAMPLE_RATE   = 16000
CHUNK_SAMPLES = 960          # 每包 60ms @ 16kHz
CHUNK_BYTES   = CHUNK_SAMPLES * 2  # 16bit = 2 bytes/sample


def cprint(color: str, msg: str):
    print(f'{color}{msg}{_NC}', flush=True)


class TtsNode(Node):
    def __init__(self):
        super().__init__('tts_node')

        self.declare_parameter('language', 'zh')
        self.declare_parameter('speed', 150)
        self.declare_parameter('amplitude', 100)
        self.declare_parameter('queue_size', 5)
        self.declare_parameter('tts_topic', '/tts_text')
        self.declare_parameter('audio_topic', '/audiosender')

        self._lang       = self.get_parameter('language').value
        self._speed      = self.get_parameter('speed').value
        self._amp        = self.get_parameter('amplitude').value
        q_size           = self.get_parameter('queue_size').value
        tts_topic        = self.get_parameter('tts_topic').value
        audio_topic      = self.get_parameter('audio_topic').value

        # 动态导入 unitree_go 消息类型
        try:
            from unitree_go.msg import AudioData
            self._AudioData = AudioData
        except ImportError:
            self.get_logger().error(
                'unitree_go 包未找到，请 source unitree_ros2 的 setup.bash')
            raise

        self._queue: queue.Queue = queue.Queue(maxsize=q_size)
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        self._pub_audio = self.create_publisher(
            self._AudioData, audio_topic, 10)

        self.create_subscription(String, tts_topic, self._tts_cb, 10)

        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

        cprint(_C, f'[TTS] 节点启动  话题={tts_topic} → {audio_topic}  '
                   f'语言={self._lang}  语速={self._speed}')

    def _tts_cb(self, msg: String):
        text = msg.data.strip()
        if not text:
            self._interrupt()
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

    def _interrupt(self):
        cprint(_Y, '[TTS] 中断播报，清空队列')
        self._stop_event.set()
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def _synth_pcm(self, text: str) -> bytes:
        """用 espeak-ng 合成 16000Hz / mono / 16bit PCM，返回原始字节。"""
        cmd = [
            'espeak-ng',
            '-v', self._lang,
            '-s', str(self._speed),
            '-a', str(self._amp),
            '-r', '16000',       # 采样率
            '--stdout',
            text,
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, timeout=30)
            if result.returncode != 0:
                cprint(_Y, f'[TTS] espeak-ng 错误: '
                           f'{result.stderr.decode(errors="replace")[:100]}')
                return b''
            wav = result.stdout
            # 跳过 WAV 头（44 字节），取原始 PCM
            return wav[44:] if len(wav) > 44 else b''
        except subprocess.TimeoutExpired:
            cprint(_Y, '[TTS] espeak-ng 超时')
            return b''
        except FileNotFoundError:
            cprint(_Y, '[TTS] 未找到 espeak-ng，请: sudo apt install espeak-ng')
            return b''

    def _publish_pcm(self, pcm: bytes):
        """将 PCM 数据按 60ms 分块发布到 /audiosender。"""
        self._stop_event.clear()
        total = len(pcm)
        offset = 0
        t_frame = 0

        while offset < total:
            if self._stop_event.is_set():
                cprint(_Y, '[TTS] 播报被中断')
                return

            chunk = pcm[offset: offset + CHUNK_BYTES]
            offset += CHUNK_BYTES

            # 不足一包时补零对齐
            if len(chunk) < CHUNK_BYTES:
                chunk = chunk + b'\x00' * (CHUNK_BYTES - len(chunk))

            msg = self._AudioData()
            msg.time_frame = t_frame
            msg.data = array.array('B', chunk)
            self._pub_audio.publish(msg)

            t_frame += 1
            time.sleep(0.06)   # 60ms/包，与采样率匹配

    def _speak(self, text: str):
        cprint(_G, f'[TTS] 合成并播报: {text}')
        pcm = self._synth_pcm(text)
        if pcm:
            self._publish_pcm(pcm)

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
