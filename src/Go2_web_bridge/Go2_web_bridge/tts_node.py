#!/usr/bin/env python3
"""
TTS 语音播报节点

订阅 /tts_text (std_msgs/String)，通过 espeak-ng + aplay 直接驱动
ALSA 音频设备（默认 plughw:2,0 = USB Audio Device），完全绕开 PulseAudio。
"""

import queue
import subprocess
import threading

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

_G  = '\033[0;32m'
_Y  = '\033[1;33m'
_C  = '\033[0;36m'
_NC = '\033[0m'


def cprint(color: str, msg: str):
    print(f'{color}{msg}{_NC}', flush=True)


class TtsNode(Node):
    def __init__(self):
        super().__init__('tts_node')

        self.declare_parameter('queue_size',   5)
        self.declare_parameter('tts_topic',    '/tts_text')
        self.declare_parameter('alsa_device',  'plughw:2,0')
        self.declare_parameter('language',     'zh')
        self.declare_parameter('speed',        150)
        self.declare_parameter('amplitude',    100)

        q_size          = self.get_parameter('queue_size').value
        tts_topic       = self.get_parameter('tts_topic').value
        self._device    = self.get_parameter('alsa_device').value
        self._lang      = self.get_parameter('language').value
        self._speed     = self.get_parameter('speed').value
        self._amplitude = self.get_parameter('amplitude').value

        self.create_subscription(String, tts_topic, self._tts_cb, 10)

        self._queue: queue.Queue = queue.Queue(maxsize=q_size)
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

        cprint(_C, f'[TTS] 节点启动  话题={tts_topic}  设备={self._device}  语言={self._lang}')

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
        try:
            # pasuspender 临时挂起 PulseAudio，让 aplay 直接访问 ALSA 设备
            cmd = (
                f"espeak-ng -v {self._lang} -s {self._speed} -a {self._amplitude}"
                f" --stdout {subprocess.list2cmdline([text])}"
                f" | aplay -D {self._device} -q"
            )
            subprocess.run(
                ['pasuspender', '--', 'bash', '-c', cmd],
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError as e:
            cprint(_Y, f'[TTS] 命令未找到: {e}  (请安装 espeak-ng / alsa-utils / pulseaudio-utils)')
        except Exception as e:
            cprint(_Y, f'[TTS] 播报失败: {e}')

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
