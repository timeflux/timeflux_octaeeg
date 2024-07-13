"""OctaEEG Driver"""

import websocket
import socket
import numpy as np
from timeflux.core.node import Node
from timeflux.core.exceptions import WorkerInterrupt
from timeflux.helpers.clock import now
from threading import Thread, Lock


RATES = { 250: 0x06, 500: 0x05, 1000: 0x04, 2000: 0x03, 4000: 0x02, 8000: 0x01, 16000: 0x00 }
GAINS = { 1: 0xC0, 2: 0xC1, 4:0xC2, 6: 0xC3, 8: 0xC4, 12: 0xC5, 24: 0xC6 }
CHANNELS = 8

class OctaEEG(Node):

    """OctaEEG Driver.

    Args:
        port (string): The serial port.
            e.g. ``COM3`` on Windows;  ``/dev/cu.usbmodem14601`` on MacOS;
            ``/dev/ttyUSB0`` on GNU/Linux.
        rate (int): The device rate in Hz.
            Allowed values: ``250``, ``500``, ``1024``, ``2048``, ``4096``, ``8192``,
            ``16384``. Default: ``250``.
        gain (int): The amplifier gain.
            Allowed values: ``1``, ``2``, ``4``, ``6``, ``8``, ``12``, ``24``.
            Default: ``24``.
        names (int): The number of channels to enable. Default: ``8``.

    Attributes:
        o (Port): Default output, provides DataFrame.

    Example:
        .. literalinclude:: /../examples/test.yaml
           :language: yaml
    """

    def __init__(self, rate=250, gain=1, names=None):

        # Validate input
        if rate not in RATES:
            raise ValueError(
                f"`{rate}` is not a valid rate; valid rates are: {sorted(RATES.keys())}"
            )
        if gain not in GAINS.keys():
            raise ValueError(
                f"`{gain}` is not a valid gain; valid gains are: {sorted(GAINS.keys())}"
            )
        self.rate = rate
        self.gain = gain

        # Set channel names
        if isinstance(names, list) and len(names) == CHANNELS:
            self.names = names
        else:
            self.names = list(range(1, CHANNELS + 1))

        # Connect
        self._ws = websocket.WebSocket()
        try:
            self._ws.connect(f"ws://{socket.gethostbyname('oric.local')}:81")
            self.logger.debug("Connected")
        except:
            raise WorkerInterrupt("Could not connect to device")

        # Set sampling rate and gain
        self._set_sampling_rate(rate)
        self._set_gain(gain)

        # Compute time offset
        # TODO

        # Set meta
        self.meta = { "rate": rate }

        # Launch background thread
        self._reset()
        self._lock = Lock()
        self._running = True
        self._thread = Thread(target=self._loop).start()


    def _set_sampling_rate(self, rate, fps=1):
        """Set sampling rate."""
        # TODO: configure FPS
        if rate in RATES:
            byte = RATES[rate] << 1
            command = 0x80 | byte | fps
            self._ws.send_binary(command.to_bytes(1, byteorder="big"))


    def _set_gain(self, gain):
        """Set gain."""
        # TODO: set gain per channel
        if gain in GAINS:
            self._ws.send_binary(GAINS[gain].to_bytes(1, byteorder="big"))


    def _reset(self):
        """Empty cache."""
        self._rows = []
        self._timestamps = []


    def _loop(self):
        """Acquire and cache data."""
        delta = np.timedelta64(np.int64(1e9 / self.rate), "ns")
        while self._running:
            #try:
            timestamp, data = self._read()
            timestamps = [timestamp]
            for i in range(len(data) - 1):
                timestamps.append(timestamps[-1] - delta)
            timestamps.reverse()
            if data:
                self._lock.acquire()
                self._timestamps += timestamps
                self._rows += data
                self._lock.release()
            # except:
            #     pass


    def _read(self):
        """Receive packets from the device."""
        data = self._ws.recv()
        timestamp = now() # TODO: adjust for latency
        block_size = 32
        rows = []
        for block_index in range(0, len(data), block_size):
            block = data[block_index:block_index + block_size]
            counter = block[0] # TODO: check for packet loss
            row = []
            for channel in range(0, CHANNELS):
                # TODO: check impedance
                channel_offset = 1 + (channel * 3)
                sample = int.from_bytes(block[channel_offset:channel_offset + 3], byteorder="big", signed=True)
                sample *= (1e6 * ((4.5 / 8388607) / self.gain))
                row.append(sample)
            rows.append(row)
        return timestamp, rows


    def update(self):
        """Update the node output."""
        self._lock.acquire()
        if self._rows:
            self.o.set(self._rows, self._timestamps, self.names, meta=self.meta)
            self._reset()
        self._lock.release()


    def terminate(self):
        """Cleanup."""
        self._running = False
        while self._thread and self._thread.is_alive():
            sleep(0.001)


