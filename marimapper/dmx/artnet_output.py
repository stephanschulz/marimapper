"""Art-Net output via stupidArtnet (matches artnet_gui.py behaviour)."""

from __future__ import annotations

from stupidArtnet import StupidArtnet


class ArtnetOutput:
    """Multi-universe Art-Net sender with optional ArtSync."""

    def __init__(
        self,
        target_ip: str = "192.168.1.255",
        universe_start: int = 0,
        universe_end: int = 0,
        fps: int = 40,
        use_artsync: bool = False,
    ):
        self.target_ip = target_ip.strip()
        self.universe_start = universe_start
        self.universe_end = universe_end
        self.fps = fps
        self.use_artsync = use_artsync
        self._senders: list[StupidArtnet] = []

    @property
    def universe_count(self) -> int:
        return max(0, self.universe_end - self.universe_start + 1)

    def rebuild(self) -> int:
        for sender in self._senders:
            sender.stop()
        self._senders.clear()

        if self.universe_end < self.universe_start:
            self.universe_start, self.universe_end = (
                self.universe_end,
                self.universe_start,
            )

        is_broadcast = self.target_ip.endswith(".255")
        for universe in range(self.universe_start, self.universe_end + 1):
            # Do not pass artsync=True: one ArtSync after all universes (see send_packets).
            sender = StupidArtnet(
                self.target_ip,
                universe,
                512,
                self.fps,
                is_broadcast,
                is_broadcast,
            )
            self._senders.append(sender)
        return len(self._senders)

    def send_packets(self, packets: list[bytearray]) -> int:
        """Send one 512-channel buffer per universe. Returns send error count."""
        if not self._senders:
            return 0

        err_count = 0
        for index, sender in enumerate(self._senders):
            packet = packets[index] if index < len(packets) else packets[-1]
            sender.set(packet)
            try:
                sender.show()
            except OSError:
                err_count += 1

        if self.use_artsync and self._senders:
            try:
                self._senders[0].send_artsync()
            except OSError:
                err_count += 1
        return err_count

    def send_universe(self, universe_index: int, data: bytearray | bytes) -> None:
        if universe_index < 0 or universe_index >= len(self._senders):
            return
        self._senders[universe_index].set(data)
        self._senders[universe_index].show()

    def stop(self) -> None:
        for sender in self._senders:
            sender.stop()
        self._senders.clear()
