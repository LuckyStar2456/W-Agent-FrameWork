from pathlib import Path

class SecurityError(Exception):
    """安全异常"""
    pass

class SkillVerifier:
    def __init__(self, public_key_path: Path):
        from cryptography.hazmat.primitives.asymmetric import ed25519
        with open(public_key_path, "rb") as f:
            self.public_key = ed25519.Ed25519PublicKey.from_public_bytes(f.read())
    
    def verify(self, skill_path: Path) -> bool:
        signature_path = skill_path / "SKILL.sig"
        if not signature_path.exists():
            raise SecurityError("Missing signature file")
        content = (skill_path / "SKILL.md").read_bytes()
        signature = signature_path.read_bytes()
        try:
            self.public_key.verify(signature, content)
            return True
        except Exception:
            return False