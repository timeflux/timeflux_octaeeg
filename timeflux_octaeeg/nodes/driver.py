"""OctaEEG Driver"""

import websocket
import json
import socket
import numpy as np
from timeflux.core.node import Node
from timeflux.core.exceptions import WorkerInterrupt
from timeflux.helpers.clock import now
from threading import Thread, Lock


# RATES = { 250: 0x96, 500: 0x95, 1000: 0x94, 2000: 0x93, 4000: 0x92, 8000: 0x91, 16000: 0x90 }
RATES = { 250: 0x96, 500: 0x95, 1000: 0x94, 2000: 0x93, 4000: 0x92, 8000: 0x91 } # Limited to 8 kSPS for now
GAINS = { 1: 0x00, 2: 0x10, 4:0x20, 6: 0x30, 8: 0x40, 12: 0x50, 24: 0x60 }
CHANNELS = 8

class OctaEEG(Node):

    """OctaEEG Driver.

    Args:
        rate (int): The device rate in Hz.
            Allowed values: `250`, `500`, `1000`, `2000`, `4000`, `8000`.
            Default: `250`.
        gain (int): The amplifier gain.
            Allowed values: `1`, `2`, `4`, `6`, `8`, `12`, `24`.
            Default: `24`.
        names (list): The list of channels names. Default: `None`.
        debug (bool): If `True`, add the internal timestamp and counter. Default: `False`.

    Attributes:
        o (Port): Default output, provides DataFrame.

    Example:
        .. literalinclude:: /../examples/test.yaml
           :language: yaml
    """

    def __init__(self, rate=250, gain=24, names=None, debug=False):

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

        # Debug mode
        self.debug = debug

        # Set channel names
        if isinstance(names, list) and len(names) == CHANNELS:
            self.names = names
        else:
            self.names = list(range(1, CHANNELS + 1))
        if self.debug:
            self.names = ["TIMESTAMP", "COUNTER"] + self.names

        # Connect
        self._ws = websocket.WebSocket()
        try:
            self._ws.connect(f"ws://{socket.gethostbyname('oric.local')}:81")
            self.logger.debug("Connected")
        except:
            raise WorkerInterrupt("Could not connect to device")

        # Initialize the ADS1299
        # See: https://www.ti.com/lit/ds/symlink/ads1299.pdf
        self._ws.send_text(json.dumps({"command":"sdatac", "parameters":[]}))
        self._ws.send_text(json.dumps({"command":"wreg", "parameters":[0x01, RATES[rate]]}))
        self._ws.send_text(json.dumps({"command":"wreg", "parameters":[0x02, 0xC0]}))
        self._ws.send_text(json.dumps({"command":"wreg", "parameters":[0x03, 0xEC]}))
        self._ws.send_text(json.dumps({"command":"wreg", "parameters":[0x15, 0x20]}))
        self._ws.send_text(json.dumps({"command":"wreg", "parameters":[0x05, GAINS[gain]]}))
        self._ws.send_text(json.dumps({"command":"wreg", "parameters":[0x06, GAINS[gain]]}))
        self._ws.send_text(json.dumps({"command":"wreg", "parameters":[0x07, GAINS[gain]]}))
        self._ws.send_text(json.dumps({"command":"wreg", "parameters":[0x08, GAINS[gain]]}))
        self._ws.send_text(json.dumps({"command":"wreg", "parameters":[0x09, GAINS[gain]]}))
        self._ws.send_text(json.dumps({"command":"wreg", "parameters":[0x0A, GAINS[gain]]}))
        self._ws.send_text(json.dumps({"command":"wreg", "parameters":[0x0B, GAINS[gain]]}))
        self._ws.send_text(json.dumps({"command":"wreg", "parameters":[0x0C, GAINS[gain]]}))
        self._ws.send_text(json.dumps({"command":"status", "parameters":[]}))
        self._ws.send_text(json.dumps({"command":"rdatac", "parameters":[]}))

        # Set meta
        self.meta = { "rate": rate }

        # Launch background thread
        self._reset()
        self._lock = Lock()
        self._running = True
        self._thread = Thread(target=self._loop).start()


    def _reset(self):
        """Empty cache."""
        self._rows = []
        self._timestamps = []


    def _loop(self):
        """Acquire and cache data."""
        self.delta = None
        self.last = 0
        while self._running:
            timestamps, data = self._read()
            if data:
                self._lock.acquire()
                self._rows += data
                self._timestamps += timestamps
                self._lock.release()


    def _read(self):
        """Receive packets from the device."""
        data = self._ws.recv()
        block_size = 32
        timestamps = []
        rows = []
        if data and (type(data) is list or type(data) is bytes):
            # TODO: check impedance
            # TODO: check for missing or out of order packets
            for block_index in range(0, len(data), block_size):
                block = data[block_index:block_index + block_size]
                timestamp = int.from_bytes(block[0:4], byteorder="little")
                counter = int.from_bytes(block[4:8], byteorder="little")
                row = [timestamp, counter] if self.debug else []
                if self.delta == None or self.last >= timestamp:
                    # Make sure that the signal is not drifting and that we handle timestamp overflow properly
                    self.delta = now() - np.datetime64(timestamp, "us")
                self.last = timestamp
                for channel in range(0, CHANNELS):
                    channel_offset = 8 + (channel * 3)
                    sample = int.from_bytes(block[channel_offset:channel_offset + 3], byteorder="big", signed=True)
                    sample *= (1e6 * ((4.5 / 8388607) / self.gain)) # raw value to uV
                    row.append(sample)
                rows.append(row)
                timestamps.append(np.datetime64(timestamp, "us") + self.delta)
        return timestamps, rows


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


