import pytest
from cryptography.fernet import Fernet

from rts.config import Settings
from rts.security.crypto import SecretBox, SecretDecryptError, SecretKeyError, load_secret_key
from rts.security.masking import SecretMasker, mask_secrets


def test_encrypt_roundtrip_and_tokens_differ():
    box = SecretBox(Fernet.generate_key())
    t1, t2 = box.encrypt("s3cr3t"), box.encrypt("s3cr3t")
    assert t1 != t2 and "s3cr3t" not in t1
    assert box.decrypt(t1) == "s3cr3t"


def test_decrypt_with_wrong_key_fails():
    token = SecretBox(Fernet.generate_key()).encrypt("x")
    with pytest.raises(SecretDecryptError):
        SecretBox(Fernet.generate_key()).decrypt(token)


def test_invalid_key_has_helpful_message():
    with pytest.raises(SecretKeyError, match="Fernet"):
        SecretBox(b"not-a-valid-key")


def test_key_is_generated_once_and_reused(tmp_path, caplog):
    settings = Settings(data_dir=tmp_path, secret_key=None, _env_file=None)
    with caplog.at_level("WARNING"):
        key1 = load_secret_key(settings)
    assert settings.secret_key_file.exists()
    assert "nova chave foi gerada" in caplog.text
    assert load_secret_key(settings) == key1


def test_env_key_takes_precedence(tmp_path):
    env_key = Fernet.generate_key().decode()
    settings = Settings(data_dir=tmp_path, secret_key=env_key, _env_file=None)
    assert load_secret_key(settings) == env_key.encode()
    assert not settings.secret_key_file.exists()


def test_masking_replaces_all_occurrences_longest_first():
    text = "token=abc123 again abc123 and abc"
    assert mask_secrets(text, ["abc", "abc123"]) == "token=**** again **** and ****"


def test_masking_handles_regex_chars_and_empty_values():
    masker = SecretMasker(["a.b*c", "", None])
    assert masker.mask("x a.b*c y aXbc") == "x **** y aXbc"
    assert not SecretMasker([])
    assert SecretMasker([]).mask("abc") == "abc"
