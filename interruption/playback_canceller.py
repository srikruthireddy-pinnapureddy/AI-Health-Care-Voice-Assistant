from tts.playback_manager import PlaybackManager


class PlaybackCanceller:
    def __init__(self, playback_manager: PlaybackManager) -> None:
        self._playback = playback_manager

    async def cancel(self, call_sid: str) -> None:
        await self._playback.cancel(call_sid)
