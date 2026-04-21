import msgpack
import zstd
from pathlib import Path
from typing import Optional
from w_agent.scanner.parallel_scanner import ScanResult

class ScannerCache:
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(exist_ok=True)
    
    def _save_cache(self, cache_key: str, result: ScanResult):
        data = msgpack.packb(result.to_dict(), use_bin_type=True)
        compressed = zstd.compress(data, level=3)
        (self.cache_dir / f"{cache_key}.cmp").write_bytes(compressed)
    
    def _load_cache(self, cache_key: str) -> ScanResult:
        compressed = (self.cache_dir / f"{cache_key}.cmp").read_bytes()
        data = zstd.decompress(compressed)
        return ScanResult.from_dict(msgpack.unpackb(data))
    
    def get(self, cache_key: str) -> Optional[ScanResult]:
        """获取缓存"""
        cache_file = self.cache_dir / f"{cache_key}.cmp"
        if cache_file.exists():
            return self._load_cache(cache_key)
        return None
    
    def set(self, cache_key: str, result: ScanResult):
        """设置缓存"""
        self._save_cache(cache_key, result)