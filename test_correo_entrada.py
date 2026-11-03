"""correo_entrada: .eml real y un .msg sintético construido aquí (escritor CFB mínimo con ministream, propiedades MAPI)."""
import struct
from email.message import EmailMessage

import pytest

import correo_entrada as CE

FIN, LIBRE, FAT = 0xFFFFFFFE, 0xFFFFFFFF, 0xFFFFFFFD


def cfb(arbol):
    """arbol: {nombre: bytes | {…}} -> bytes de un CFB v3 (sector 512, ministream <4096). Un solo sector FAT (≤128 sectores)."""
    ents = [{"n": "Root Entry", "t": 5, "h": None, "d": b""}]

    def add(d, padre):
        ids = []
        for n, v in d.items():
            e = {"n": n, "t": 1 if isinstance(v, dict) else 2, "h": None, "d": b"" if isinstance(v, dict) else v}
            ents.append(e)
            ids.append(len(ents) - 1)
            isinstance(v, dict) and add(v, e)
        for a, b in zip(ids, ids[1:]):
            ents[a]["r"] = b  # hermanos en cadena por «derecha»
        padre["h"] = ids[0] if ids else None

    add(arbol, ents[0])
    sec = lambda b: [b[i:i + 512].ljust(512, b"\0") for i in range(0, len(b), 512)]
    mini, minifat = b"", []
    for e in ents[1:]:
        if e["t"] == 2 and len(e["d"]) < 4096:
            n = -(-len(e["d"]) // 64)
            e["s"] = len(minifat) if n else FIN
            minifat += [len(minifat) + i + 1 for i in range(n - 1)] + [FIN] * (n > 0)
            mini += e["d"].ljust(n * 64, b"\0")
    secs, fat = [], []

    def put(b):
        s = sec(b)
        ini = len(secs) if s else FIN
        fat.extend([ini + i + 1 for i in range(len(s) - 1)] + [FIN] * (len(s) > 0))
        secs.extend(s)
        return ini
    ents[0]["s"], ents[0]["z"] = put(mini), len(mini)
    mf = put(b"".join(struct.pack("<I", x) for x in minifat)) if minifat else FIN
    for e in ents[1:]:
        e["z"] = len(e["d"]) if e["t"] == 2 else 0
        if e["t"] == 2 and len(e["d"]) >= 4096:
            e["s"] = put(e["d"])
    raw = b""
    for e in ents:
        nm = e["n"].encode("utf-16-le")
        raw += nm.ljust(64, b"\0") + struct.pack("<HBBIII", len(nm) + 2, e["t"], 1, LIBRE, e.get("r", LIBRE), LIBRE if e["h"] is None else e["h"]) + b"\0" * 36
        raw += struct.pack("<IQ", e.get("s", FIN), e["z"])
    d0 = put(raw.ljust(-(-len(raw) // 512) * 512, b"\0"))
    fat_i = len(secs)
    fat.append(FAT)
    fat += [LIBRE] * (128 - len(fat))
    assert len(fat) == 128
    secs.append(b"".join(struct.pack("<I", x) for x in fat))
    h = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 16 + struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6) + b"\0" * 6 + struct.pack("<I", 0)
    h += struct.pack("<IIIIIIIII", 1, d0, 0, 4096, mf, 1 if minifat else 0, FIN, 0, fat_i) + struct.pack("<108I", *[LIBRE] * 108)
    return h.ljust(512, b"\0") + b"".join(secs)


def u(t):
    return t.encode("utf-16-le")


def msg_fixture(html_only=False, grande=False):
    props = b"\0" * 32 + struct.pack("<IIQ", 0x00390040, 6, (1_800_000_000 + 11644473600) * 10_000_000)  # 2027-01-15
    adj = {"__substg1.0_37010102": b"%PDF-" + (b"x" * 5000 if grande else b"1"), "__substg1.0_3707001F": u("acta.pdf")}
    cuerpo = ({"__substg1.0_10130102": b"<html><head><style>p{}</style></head><body><p>Hola <b>equipo</b></p><ul><li>uno</li></ul></body></html>"} if html_only
              else {"__substg1.0_1000001F": u("Hola equipo, ñandú.")})
    return cfb({"__properties_version1.0": props, "__substg1.0_0037001F": u("Reunión del lunes"), "__substg1.0_0C1A001F": u("Ana Pérez"),
                "__substg1.0_5D01001F": u("ana@ejemplo.es"), **cuerpo, "__attach_version1.0_#00000000": adj})


def test_msg_texto_adjunto_fecha(tmp_path):
    p = tmp_path / "a.msg"
    p.write_bytes(msg_fixture(grande=True))
    r = CE.leer(p)
    assert r["asunto"] == "Reunión del lunes" and r["de"] == "Ana Pérez <ana@ejemplo.es>" and r["texto"] == "Hola equipo, ñandú."
    assert r["fecha"].startswith("2027-01-15") and r["adjuntos"] == [{"nombre": "acta.pdf", "datos": b"%PDF-" + b"x" * 5000}]


def test_msg_html(tmp_path):
    p = tmp_path / "b.msg"
    p.write_bytes(msg_fixture(html_only=True))
    t = CE.leer(p)["texto"]
    assert "Hola equipo" in t and "uno" in t and "p{}" not in t and "<" not in t


def test_cfb_invalido():
    with pytest.raises(ValueError):
        CE.CFB(b"no es un cfb" * 100)


def test_eml(tmp_path):
    m = EmailMessage()
    m["Subject"], m["From"], m["To"], m["Date"] = "Resumen ñ", "Luis <luis@x.es>", "a@b.c", "Mon, 02 Nov 2026 10:00:00 +0100"
    m.set_content("texto plano")
    m.add_alternative("<p>html <b>rico</b></p>", subtype="html")
    m.add_attachment(b"datos", maintype="application", subtype="octet-stream", filename="f.bin")
    p = tmp_path / "c.eml"
    p.write_bytes(bytes(m))
    r = CE.leer(p)
    assert r["asunto"] == "Resumen ñ" and "luis@x.es" in r["de"] and r["texto"] == "texto plano" and r["fecha"].startswith("2026-11-02T10:00")
    assert r["adjuntos"] == [{"nombre": "f.bin", "datos": b"datos"}]
    m2 = EmailMessage()
    m2["Subject"] = "solo html"
    m2.set_content("<p>solo <i>html</i></p>", subtype="html")
    (tmp_path / "d.eml").write_bytes(bytes(m2))
    assert CE.leer(tmp_path / "d.eml")["texto"] == "solo html"


def test_outlook_endpoint_motivo_claro(monkeypatch):
    import app
    from fastapi.testclient import TestClient
    from pathlib import Path
    import tempfile
    d = Path(tempfile.mkdtemp())
    monkeypatch.setattr(app.pipeline, "WORK", d)
    (d / "m1" / "v1" / "correos").mkdir(parents=True)
    (d / "m1" / "v1" / "correos" / "0.eml").write_bytes(b"To: a@b.es\r\nSubject: Hola\r\nContent-Type: text/html\r\n\r\n<p>x</p>")
    vistos = []
    monkeypatch.setattr(app.correo, "abrir_outlook", lambda cor, pdf=None, nombre_pdf="": vistos.append((cor, pdf)))
    c = TestClient(app.app)
    assert c.post("/api/correo/m1/v1/outlook/0").json() == {"ok": True}
    assert vistos[0][0]["para"] == "a@b.es" and vistos[0][0]["asunto"] == "Hola" and "<p>x</p>" in vistos[0][0]["html"] and vistos[0][1] is None
    def no(*a, **k):
        raise RuntimeError("Outlook clásico no está disponible")
    monkeypatch.setattr(app.correo, "abrir_outlook", no)
    r = c.post("/api/correo/m1/v1/outlook/0")
    assert r.status_code == 400 and "Outlook" in r.json()["detail"]
    assert c.post("/api/correo/m1/v1/outlook/9").status_code == 404
