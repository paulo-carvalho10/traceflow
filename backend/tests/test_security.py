from __future__ import annotations

import time

import jwt

from traceflow import security

SECRET = "segredo-de-teste-com-pelo-menos-32-bytes"
OTHER = "outro-segredo-de-teste-com-32-bytes-ou-mais"


def test_senha_confere_e_o_hash_nao_e_a_senha() -> None:
    h = security.hash_password("correta-cavalo-bateria")
    assert h.startswith("$argon2id$") and "correta" not in h
    assert security.verify_password("correta-cavalo-bateria", h)
    assert not security.verify_password("errada-cavalo-bateria", h)


def test_mesma_senha_gera_hashes_diferentes() -> None:
    # o sal aleatório: duas contas com a mesma senha não têm o mesmo hash
    assert security.hash_password("mesma-senha-123") != security.hash_password("mesma-senha-123")


def test_conta_sem_senha_nunca_confere() -> None:
    assert not security.verify_password("qualquer-coisa", None)
    assert not security.verify_password("x", "isto-nao-e-um-hash")


def test_chave_nova_tem_o_formato_e_so_o_hash_do_segredo() -> None:
    key = security.generate_key()
    parsed = security.parse_key(key.full)
    assert parsed is not None
    prefix, secret = parsed
    assert prefix == key.prefix and len(prefix) == 8
    assert len(secret) == 32
    assert secret not in key.secret_hash
    assert security.secret_matches(secret, key.secret_hash)
    assert not security.secret_matches(secret + "x", key.secret_hash)


def test_chaves_mal_formadas_sao_recusadas() -> None:
    for bad in ["", "tf_", "tf_ABCDEFGH_" + "a" * 32, "tf_abc_" + "a" * 32, "xx_abcdefgh_" + "a" * 32,
                "tf_abcdefgh_curto"]:  # fmt: skip
        assert security.parse_key(bad) is None, bad


def test_sessao_ida_e_volta() -> None:
    token = security.create_session_token(42, SECRET, hours=1)
    session = security.read_session_token(token, SECRET)
    assert session is not None and session.user_id == 42


def test_sessao_vencida_adulterada_ou_com_outro_segredo_e_recusada() -> None:
    old = security.create_session_token(42, SECRET, hours=1, now=time.time() - 7200)
    assert security.read_session_token(old, SECRET) is None
    assert security.read_session_token(security.create_session_token(42, OTHER, hours=1), SECRET) is None
    claims = jwt.decode(
        security.create_session_token(42, SECRET, hours=1), options={"verify_signature": False}
    )
    forged = jwt.encode(
        {**claims, "sub": "1"}, "chute-" + "x" * 32, algorithm="HS256"
    )  # tenta virar o usuário 1
    assert security.read_session_token(forged, SECRET) is None
    assert security.read_session_token("lixo", SECRET) is None


def test_sessao_sem_algoritmo_none() -> None:
    # o ataque clássico: um token "sem assinatura" (alg=none) não pode ser aceito
    unsigned = jwt.encode(
        {"sub": "1", "iat": int(time.time()), "exp": int(time.time()) + 60}, None, algorithm="none"
    )
    assert security.read_session_token(unsigned, SECRET) is None


def test_segredo_curto_impede_a_api_de_subir() -> None:
    import pytest
    from pydantic import ValidationError

    from traceflow.config import Settings

    with pytest.raises(ValidationError):
        Settings(jwt_secret="curto")
