import socket
import threading
import time
from pathlib import Path

import pytest

from gogoham.contests import CONTESTS, Qso, Scorer, Station, wpx_prefix
from gogoham.cty import CtyDB
from gogoham.db import LogDB
from gogoham.export import adif, cabrillo
from gogoham.locator import grid_distance_km
from gogoham.rig import RigWorker
from gogoham.wsjtx import (adif_to_qso, build_logged_adif_packet, parse_adif_file,
                              parse_packet)

HERE = Path(__file__).parent


@pytest.fixture(scope="module")
def cty():
    return CtyDB.from_file(HERE / "cty_sample.dat")


def make(cid, cty, call="DL1ABC", zone=14, grid="JN59"):
    c = CONTESTS[cid](cty, Station(call=call, cq_zone=zone, grid=grid))
    return c, Scorer(c)


def q(call, band="20", mode="USB", exch_r="", qid=None, exch_s="14", t="2026-10-24 00:01:00"):
    return Qso(id=qid, time=t, call=call, band=band, mode=mode, freq=0,
               rst_s="59", exch_s=exch_s, rst_r="59", exch_r=exch_r)


# ------------------------------------------------------------------ CQ WW
def test_cqww_points_and_mults(cty):
    c, s = make("cqww-ssb", cty)
    log = [q("W1AW", exch_r="05", qid=1),       # anderer Kontinent: 3
           q("OE1XYZ", exch_r="15", qid=2),     # gleicher Kontinent: 1
           q("DL2XYZ", exch_r="14", qid=3),     # eigenes Land: 0, aber Multi
           q("W1AW", exch_r="05", qid=4),       # Dupe
           q("W1AW", band="40", exch_r="05", qid=5)]  # neues Band: 3, neue Multis
    s.rebuild(log)
    assert s.total_points == 3 + 1 + 0 + 3
    assert s.dupes == 1
    # Zonen: 20m {5,15,14}, 40m {5}; Länder: 20m {K,OE,DL}, 40m {K}
    assert s.mult_count("zone") == 4
    assert s.mult_count("country") == 4
    assert s.score == 7 * 8


def test_cqww_na_rule(cty):
    c, s = make("cqww-ssb", cty, call="W1AW", zone=5)
    ev = s.evaluate(q("VE3ABC", exch_r="04"))
    assert ev.points == 2
    ev = s.evaluate(q("K6XX", exch_r="03"))
    assert ev.points == 0


def test_cqww_live_check(cty):
    c, s = make("cqww-ssb", cty)
    s.evaluate(q("JA1ABC", exch_r="25", qid=1), commit=True)
    ev = s.evaluate(q("JA1ABC", exch_r="25"))
    assert ev.dupe
    ev = s.evaluate(q("JA1ABC", band="15", exch_r="25"))
    assert not ev.dupe and ("zone", "25") in ev.new_mults and ev.points == 3
    ev = s.evaluate(q("JA2XYZ", exch_r="25"))
    assert ev.new_mults == []


def test_cqww_wrong_mode_and_band(cty):
    c, s = make("cqww-ssb", cty)
    ev = s.evaluate(q("W1AW", mode="CW", exch_r="05"))
    assert not ev.valid and ev.points == 0
    ev = s.evaluate(q("W1AW", band="30", exch_r="05"))
    assert not ev.valid


def test_cqww_multi_zone_prefill(cty):
    c, s = make("cqww-ssb", cty)
    assert c.default_rcvd_exchange(cty.lookup("DL2XYZ")) == "14"
    assert c.default_rcvd_exchange(cty.lookup("JA1ABC")) == "25"
    # Testdatei wie die echte cty.dat: VK ohne CQ-Zonen-Ausnahmen
    for call in ("VK", "VK2ABC", "VK6ABC", "W1AW", "K6XX", "VE3ABC", "BY1AA", "UA9ABC"):
        assert c.default_rcvd_exchange(cty.lookup(call)) == "", call
    assert sorted(cty.zones_for(cty.lookup("VK3ABC"))) == [29, 30]
    info = c.describe(q("VK2ABC"), cty.lookup("VK2ABC"))
    assert "Zone erfragen" in info and "29, 30" in info
    info = c.describe(q("VK2ABC", exch_r="14"), cty.lookup("VK2ABC"))
    assert "ungewöhnlich" in info
    # ohne Zone: Land zählt schon, Zone noch nicht
    ev = s.evaluate(q("VK2ABC", exch_r=""))
    assert ev.new_mults == [("country", "VK")]
    ev = s.evaluate(q("VK2ABC", exch_r="30"))
    assert ("zone", "30") in ev.new_mults


def test_cqww_maritime_zone_only(cty):
    c, s = make("cqww-ssb", cty)
    ev = s.evaluate(q("PA3XYZ/MM", exch_r="33"))
    assert ev.mults == [("zone", "33")]


# -------------------------------------------------------------------- WPX
@pytest.mark.parametrize("call,pfx", [
    ("DL1ABC", "DL1"), ("N8BJQ", "N8"), ("4X1AB", "4X1"), ("2E0ABC", "2E0"),
    ("LY2000X", "LY2000"), ("3DA0RS", "3DA0"), ("RAEM", "RA0"),
    ("N8BJQ/4", "N4"), ("DL/W1AW", "DL0"), ("W1AW/KH6", "KH6"),
    ("DL1ABC/P", "DL1"), ("PA/DL1ABC/P", "PA0"), ("OH2BH/OH0", "OH0"),
    ("9A1A", "9A1"), ("DL1ABC/QRP", "DL1"),
])
def test_wpx_prefix(call, pfx):
    assert wpx_prefix(call) == pfx


def test_wpx_points(cty):
    c, s = make("wpx-ssb", cty)
    log = [q("W1AW", band="20", exch_r="1", qid=1),    # 3
           q("W1AW", band="40", exch_r="2", qid=2),    # 6, Präfix schon da
           q("OE1XYZ", band="80", exch_r="3", qid=3),  # 2
           q("OE3XYZ", band="15", exch_r="4", qid=4),  # 1
           q("DL2XYZ", band="10", exch_r="5", qid=5)]  # eigenes Land: 1
    s.rebuild(log)
    assert s.total_points == 3 + 6 + 2 + 1 + 1
    assert s.mult_count() == 4   # W1, OE1, OE3, DL2
    assert s.score == 13 * 4


def test_wpx_na(cty):
    c, s = make("wpx-ssb", cty, call="W1AW", zone=5)
    assert s.evaluate(q("VE3ABC", band="40", exch_r="1")).points == 4
    assert s.evaluate(q("VE3ABC", band="20", exch_r="1")).points == 2
    assert s.evaluate(q("K6XX", band="20", exch_r="1")).points == 1


def test_gain(cty):
    """Wert des QSOs fürs Gesamtergebnis: 233 × 102 − 230 × 100 = 766."""
    c, s = make("cqww-ssb", cty)
    s.total_points, s.dupes = 230, 0
    s.mults = {("zone", "20"): set(str(i) for i in range(1, 41)) - {"30"},   # 39 Zonen
               ("country", "20"): set(f"X{i}" for i in range(61))}             # 61 Länder
    assert s.mult_count() == 100 and s.score == 23000
    ev = s.evaluate(q("VK2ABC", exch_r="30"))
    assert ev.points == 3 and len(ev.new_mults) == 2 and ev.gain == 766
    ev = s.evaluate(q("JA1ABC", exch_r="05"))   # Zone 5 schon da, Land JA neu
    assert ev.gain == 233 * 101 - 23000


def test_gain_in_rebuild(cty):
    c, s = make("cqww-ssb", cty)
    s.rebuild([q("W1AW", exch_r="05", qid=1), q("OE1XYZ", exch_r="15", qid=2),
               q("OE2XYZ", exch_r="15", qid=3)])
    assert [s.evals[i].gain for i in (1, 2, 3)] == [3 * 2, 4 * 4 - 6, 5 * 4 - 16]
    assert sum(s.evals[i].gain for i in (1, 2, 3)) == s.score


# ------------------------------------------------- Richtung, Locator, Infobox
def test_locator6_and_paths():
    from gogoham.locator import is_grid, latlon, paths
    assert is_grid("JN59me") and is_grid("JN59") and not is_grid("JN5")
    lat, lon = latlon("JN59me")
    assert 49.1 < lat < 49.25 and 10.95 < lon < 11.1
    # JN59 -> Sydney (QF56): SP ca. 16.300 km Richtung ~70°
    p = paths(lat, lon, *latlon("QF56od"))
    assert 15800 < p["sp_km"] < 16600 and 55 < p["sp_deg"] < 85
    assert abs(p["sp_km"] + p["lp_km"] - 40030) < 1
    assert abs((p["lp_deg"] - p["sp_deg"]) % 360 - 180) < 1e-9
    # nach Norden / Osten
    assert paths(0, 0, 10, 0)["sp_deg"] < 1
    assert abs(paths(0, 0, 0, 10)["sp_deg"] - 90) < 1e-6


def test_countries_cover_sample(cty):
    from gogoham.countries import COUNTRIES, german_name, flag_code
    for ent in cty.entities:
        assert ent.prefix.upper() in COUNTRIES, ent.prefix
    assert german_name("DL") == "Deutschland" and flag_code("DL") == "de"
    assert german_name("*GM/S") == "Shetlandinseln"
    assert german_name("XYZ", "Fallback") == "Fallback" and flag_code("XYZ") == ""


def test_infobox(cty):
    from gogoham import infobox
    c, s = make("cqww-ssb", cty, grid="JN59me")
    s.rebuild([q("VK3ABC", band="40", exch_r="30", qid=1)])
    # VK auf 20 m, Zone noch nicht eingegeben
    qq = q("VK2ABC", exch_r="")
    box = infobox.build(c, s, qq, s.evaluate(qq), "JN59me")
    assert box.name == "Australien" and box.flag == "au" and box.cont == "OC"
    texts = [t for t, _k in box.lines]
    assert texts[0] == "CQ-Zone: erfragen (29 / 30)"
    assert ("Land Australien: NEU auf 20 m (schon auf 40)", infobox.NEW) in box.lines
    assert box.path.startswith("SP ") and "LP " in box.path and "km" in box.path
    # mit Zone 30 auf 40 m -> alles schon gearbeitet bzw. Dupe-Band
    qq = q("VK2ABC", band="40", exch_r="30")
    box = infobox.build(c, s, qq, s.evaluate(qq), "JN59me")
    assert ("Zone 30: gearbeitet auf 40", infobox.WORKED) in box.lines
    assert ("Land Australien: gearbeitet auf 40", infobox.WORKED) in box.lines
    # Dupe: Infos trotzdem da
    qq = q("VK3ABC", band="40", exch_r="30")
    ev = s.evaluate(qq)
    assert ev.dupe and infobox.build(c, s, qq, ev, "JN59me").lines
    # ohne eigenen Locator
    assert "Locator" in infobox.build(c, s, qq, ev, "").path
    # ungewöhnliche Zone als Hinweis
    assert "ungewöhnlich" in c.notes(q("VK2ABC", exch_r="14"), cty.lookup("VK2ABC"))[0]


def test_infobox_wpx_and_digi(cty):
    from gogoham import infobox
    c, s = make("wpx-ssb", cty)
    s.rebuild([q("DL2XYZ", exch_r="1", qid=1)])
    qq = q("DL2ABC", band="40", exch_r="2")
    box = infobox.build(c, s, qq, s.evaluate(qq), "JN59")
    assert ("Präfix DL2: schon gearbeitet", infobox.WORKED) in box.lines
    c, s = make("ww-digi", cty, grid="JN59me")
    qq = q("W1AW", mode="FT8", exch_r="FN42")
    box = infobox.build(c, s, qq, s.evaluate(qq), "JN59me")
    assert ("Großfeld FN: NEU auf 20 m", infobox.NEW) in box.lines
    assert "SP 29" in box.path or "SP 30" in box.path or "SP 28" in box.path


def test_cty_latlon_override():
    from gogoham.cty import CtyDB
    db = CtyDB()
    db.parse("United States: 05: 08: NA: 37.53: 91.67: 5.0: K:\n    K,W6<34.0/118.0>;")
    lk = db.lookup("W6ABC")
    assert lk.lat == 34.0 and lk.lon == -118.0
    assert db.lookup("K1ABC").lat == 37.53


def test_flags_offline(tmp_path, monkeypatch):
    from gogoham import flags
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert flags.flag_path("de") is None and "de" in flags.missing_codes()
    (tmp_path / "gogoham" / "flags").mkdir(parents=True)
    (tmp_path / "gogoham" / "flags" / "de.png").write_bytes(b"\x89PNG")
    assert flags.flag_path("de") is not None and "de" not in flags.missing_codes()
    # Download ohne Netz: Fehler werden gesammelt, kein Absturz
    monkeypatch.setattr(flags, "FLAG_URL", "http://127.0.0.1:9/{code}.png")
    d = flags.FlagDownloader(["xx", "yy"], workers=2)
    d.run()
    assert d.done == 2 and sorted(d.failed) == ["xx", "yy"]



# ------------------------------------------------------------ ADIF komplett
def test_adif_complete(cty):
    from gogoham.export import adif
    from gogoham.wsjtx import parse_adif_file
    cty.dxcc = {"DL": 230, "K": 291, "VK": 150, "JA": 339, "GM": 279}
    c, s = make("cqww-ssb", cty)
    meta = {"mycall": "DO2GGH", "my_grid": "JN59me", "my_zone": "14", "operators": ""}
    qs = [q("W1AW", exch_r="05", t="2026-10-24 10:00:00"),
          q("VK2ABC", exch_r="30", t="2026-10-24 10:01:00"),
          q("JA1ABC", exch_r="25", t="2026-10-24 10:02:00"),
          q("GB2QM", exch_r="14", t="2026-10-24 10:03:00")]
    for x in qs:
        x.freq = 14_250_000
    recs = parse_adif_file(adif(c, meta, qs, {"W1AW": {"name": "Hiram", "qth": "Newington",
                                                       "grid": "FN31pr"}}))
    w, vk, ja, gm = recs
    assert w["COUNTRY"] == "United States" and w["DXCC"] == "291" and w["CONT"] == "NA"
    assert w["CQZ"] == "5" and w["PFX"] == "W1" and w["NAME"] == "Hiram"
    assert w["GRIDSQUARE"] == "FN31pr" and w["QTH"] == "Newington"
    assert w["STATION_CALLSIGN"] == "DO2GGH" and w["OPERATOR"] == "DO2GGH"
    assert w["MY_GRIDSQUARE"] == "JN59me" and w["MY_CQ_ZONE"] == "14"
    assert w["CONTEST_ID"] == "CQ-WW-SSB" and w["FREQ"] == "14.250000"
    assert vk["DXCC"] == "150" and vk["CQZ"] == "30"
    assert ja["ITUZ"] == "45" and ja["CQZ"] == "25"
    # WAE: Shetland zählt für DXCC als Schottland
    assert gm["DXCC"] == "279" and gm["COUNTRY"] == "Scotland"
    cty.dxcc = {}
    assert "DXCC" not in parse_adif_file(adif(c, meta, qs[:1]))[0]


def test_dxcc_csv():
    from gogoham.cty import parse_dxcc_csv
    good = "\n".join(["DL,Fed. Rep. of Germany,230,EU,14,28,51.0,-10.0,-1.0,DL;",
                      "K,United States,291,NA,5,8,37.5,91.7,5.0,K;",
                      "JA,Japan,339,AS,25,45,36.4,-138.4,-9.0,JA;",
                      "VK,Australia,150,OC,30,59,-23.7,-132.3,-10.0,VK;",
                      "G,England,223,EU,14,27,52.8,1.5,0.0,G;",
                      "OE,Austria,206,EU,15,28,47.3,-13.3,-1.0,OE;"])
    assert parse_dxcc_csv(good)["OE"] == 206
    assert parse_dxcc_csv(good.replace(",230,", ",999,")) == {}   # Stichprobe falsch


HAMQTH_LOGIN = """<?xml version="1.0"?><HamQTH version="2.8" xmlns="https://www.hamqth.com">
<session><session_id>abc123</session_id></session></HamQTH>"""
HAMQTH_FOUND = """<?xml version="1.0"?><HamQTH version="2.8" xmlns="https://www.hamqth.com">
<search><callsign>w1aw</callsign><nick>Hiram</nick><qth>Newington</qth><grid>fn31pr</grid>
<adr_name>ARRL HQ</adr_name></search></HamQTH>"""
HAMQTH_NOTFOUND = """<?xml version="1.0"?><HamQTH version="2.8" xmlns="https://www.hamqth.com">
<session><error>Callsign not found</error></session></HamQTH>"""
QRZ_LOGIN = """<?xml version="1.0" ?><QRZDatabase version="1.34" xmlns="http://xmldata.qrz.com">
<Session><Key>k1</Key></Session></QRZDatabase>"""
QRZ_FOUND = """<?xml version="1.0" ?><QRZDatabase version="1.34" xmlns="http://xmldata.qrz.com">
<Callsign><call>VK2ABC</call><fname>Bruce</fname><name>Smith</name><addr2>Sydney</addr2>
<grid>QF56od</grid></Callsign><Session><Key>k1</Key></Session></QRZDatabase>"""
QRZ_BADLOGIN = """<?xml version="1.0" ?><QRZDatabase version="1.34" xmlns="http://xmldata.qrz.com">
<Session><Error>Username/password incorrect</Error></Session></QRZDatabase>"""


def test_callbook_services():
    import gogoham.callbook as cb
    urls = []

    def fetch(url):
        urls.append(url)
        if "hamqth" in url:
            if "u=" in url:
                return HAMQTH_LOGIN
            return HAMQTH_FOUND if "W1AW" in url else HAMQTH_NOTFOUND
        if "username=" in url:
            return QRZ_LOGIN
        return QRZ_FOUND
    cfg = {"hamqth_user": "do2ggh", "hamqth_password": "x", "qrz_user": "do2ggh",
           "qrz_password": "y", "callbook_order": ["hamqth", "qrz"]}
    svcs = cb.services_from_config(cfg, fetch)
    assert [s.name for s in svcs] == ["HamQTH", "QRZ.com"]
    e = cb.lookup_chain(svcs, "W1AW")
    assert (e.name, e.qth, e.grid, e.source) == ("Hiram", "Newington", "FN31PR", "HamQTH")
    e = cb.lookup_chain(svcs, "VK2ABC/P")
    assert e.source == "QRZ.com" and e.name == "Bruce Smith" and e.call == "VK2ABC/P"
    assert any("callsign=VK2ABC" in u and "%2FP" not in u and "/P" not in u for u in urls)
    cfg["callbook_order"] = ["qrz", "hamqth"]
    assert [s.name for s in cb.services_from_config(cfg, fetch)] == ["QRZ.com", "HamQTH"]
    cfg["qrz_password"] = ""
    assert [s.name for s in cb.services_from_config(cfg, fetch)] == ["HamQTH"]
    bad = cb.Qrz("x", "y", lambda u: QRZ_BADLOGIN)
    errors = {}
    assert cb.lookup_chain([bad], "W1AW", errors) is None
    assert "incorrect" in errors["QRZ.com"]


def test_callbook_job():
    import gogoham.callbook as cb

    class Svc:
        name = "S"

        def lookup(self, call):
            return cb.Entry(call, name="N") if call != "XX1XX" else None
    job = cb.CallbookJob([Svc()], ["W1AW", "w1aw", "XX1XX", "JA1ABC"])
    job.start()
    job.thread.join(2)
    assert job.total == 3 and job.done == 3
    assert sorted(job.results) == ["JA1ABC", "W1AW"] and job.not_found == ["XX1XX"]


def test_db_callbook(tmp_path):
    db = LogDB(tmp_path / "c.ggh")
    db.set_callbook("w1aw", "Hiram", "Newington", "FN31PR", "HamQTH")
    assert db.callbook()["W1AW"]["name"] == "Hiram"


# ---------------------------------------------------------------- SCP
def test_scp_search():
    from gogoham.scp import ScpDB
    db = ScpDB.parse("# MASTER.SCP\nDL1ABC\nDL1ABD\nW1AW\nK1ABC\nDL1ABC\n")
    assert len(db) == 4
    assert db.search("AB") == []                       # erst ab 3 Zeichen
    assert db.search("1AB") == ["DL1ABC", "DL1ABD", "K1ABC"]
    assert db.search("1ab", extra={"VK1ABX"}) == ["DL1ABC", "DL1ABD", "K1ABC", "VK1ABX"]


# ---------------------------------------------------------------- WW Digi
def test_grid_distance():
    d = grid_distance_km("JN59", "FN42")
    assert 6000 < d < 6600


def test_wwdigi(cty):
    c, s = make("ww-digi", cty, grid="JN59")
    log = [q("W1AW", mode="FT8", exch_r="FN42", qid=1),   # ~6300 km -> 3
           q("OE1XYZ", mode="FT8", exch_r="JN88", qid=2),  # nah -> 1
           q("W1AW", mode="FT4", exch_r="FN42", qid=3),    # Dupe (egal welcher Mode)
           q("OE3XYZ", mode="FT4", exch_r="JN78", qid=4)]  # 1, Feld JN schon da
    s.rebuild(log)
    assert s.dupes == 1
    assert s.total_points == 3 + 1 + 1
    assert s.mult_count() == 2
    ev = s.evaluate(q("K1ABC", mode="USB", exch_r="FN42"))
    assert not ev.valid


# --------------------------------------------------------- DB und Export
def test_db_and_exports(tmp_path, cty):
    db = LogDB(tmp_path / "t.ggh")
    db.set_meta({"contest": "cqww-ssb", "mycall": "DL1ABC", "my_zone": "14"})
    c, s = make("cqww-ssb", cty)
    for i, call in enumerate(["W1AW", "JA1ABC", "OE1XYZ"]):
        qq = q(call, exch_r=["05", "25", "15"][i], t=f"2026-10-24 00:0{i}:00")
        qq.freq = 14_250_000
        db.add(qq)
    qs = db.all_qsos()
    assert [x.call for x in qs] == ["W1AW", "JA1ABC", "OE1XYZ"]
    s.rebuild(qs)
    cab = cabrillo(c, db.get_meta(), qs, s)
    assert "CONTEST: CQ-WW-SSB" in cab
    assert "QSO: 14250 PH 2026-10-24 0000 DL1ABC        59  14     W1AW          59  05     0" in cab
    assert f"CLAIMED-SCORE: {s.score}" in cab
    a = adif(c, db.get_meta(), qs)
    recs = parse_adif_file(a)
    assert len(recs) == 3 and recs[1]["CALL"] == "JA1ABC" and recs[1]["MODE"] == "SSB"
    qs[0].exch_r = "04"
    db.update(qs[0])
    db.delete(qs[1].id)
    assert db.count() == 2 and db.all_qsos()[0].exch_r == "04"
    db.close()


def test_wpx_serial(tmp_path):
    db = LogDB(tmp_path / "w.ggh")
    assert db.next_serial() == 1
    db.add(q("W1AW", exch_s="001"))
    db.add(q("W2AW", exch_s="002"))
    assert db.next_serial() == 3


# ----------------------------------------------------------------- WSJT-X
ADIF = ("<call:4>W1AW <gridsquare:4>FN42 <mode:4>MFSK <submode:3>FT4 "
        "<rst_sent:3>-10 <rst_rcvd:3>-05 <qso_date:8>20260829 <time_on:6>120515 "
        "<band:3>20m <freq:9>14.080500 <station_callsign:6>DL1ABC <EOR>")


def test_wsjtx_packet():
    rec = parse_packet(build_logged_adif_packet(ADIF))
    qq = adif_to_qso(rec)
    assert qq.call == "W1AW" and qq.exch_r == "FN42" and qq.mode == "FT4"
    assert qq.band == "20" and qq.freq == 14_080_500
    assert qq.time == "2026-08-29 12:05:15"
    assert parse_packet(ADIF.encode())["CALL"] == "W1AW"
    assert parse_packet(b"\x00\x01") is None


# ------------------------------------------------------- rigctld (Attrappe)
def fake_rigctld(port_holder, stop):
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port_holder.append(srv.getsockname()[1])
    srv.settimeout(3)
    conn, _ = srv.accept()
    freq, mode = [14_025_000], ["CW"]
    buf = b""
    conn.settimeout(0.2)
    while not stop.is_set():
        try:
            data = conn.recv(1024)
        except socket.timeout:
            continue
        if not data:
            break
        buf += data
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            cmd = line.decode().split()
            if cmd[0] == "f":
                conn.sendall(f"{freq[0]}\n".encode())
            elif cmd[0] == "m":
                conn.sendall(f"{mode[0]}\n500\n".encode())
            elif cmd[0] == "F":
                freq[0] = int(cmd[1])
                conn.sendall(b"RPRT 0\n")
            else:
                conn.sendall(b"RPRT 0\n")
    conn.close()
    srv.close()


def test_rig_worker():
    ports, stop = [], threading.Event()
    th = threading.Thread(target=fake_rigctld, args=(ports, stop), daemon=True)
    th.start()
    while not ports:
        time.sleep(0.01)
    w = RigWorker("127.0.0.1", ports[0], poll=0.05)
    w.start()
    deadline = time.time() + 3
    while time.time() < deadline and w.snapshot().freq != 14_025_000:
        time.sleep(0.05)
    st = w.snapshot()
    assert st.connected and st.freq == 14_025_000 and st.mode == "CW"
    w.submit("set_freq", 7_010_000)
    deadline = time.time() + 3
    while time.time() < deadline and w.snapshot().freq != 7_010_000:
        time.sleep(0.05)
    assert w.snapshot().freq == 7_010_000
    w.stop()
    w.join(2)
    stop.set()


# ------------------------------------------------------------ Log-Spalten
def test_column_defaults_per_contest():
    from gogoham import columns as colmod
    from gogoham.contests import CONTESTS
    lay = colmod.default_layout(CONTESTS["cqww-ssb"])
    vis = [k for k in lay["order"] if k not in lay["hidden"]]
    assert vis == ["nr", "utc", "band", "khz", "call", "rst_s", "ex_s", "rst_r", "ex_r",
                   "land", "pts", "gain", "mult"]
    assert {"mode", "name", "prefix", "km"} <= set(lay["hidden"])
    wpx = colmod.default_layout(CONTESTS["wpx-ssb"])
    assert "prefix" not in wpx["hidden"] and "km" in wpx["hidden"]
    digi = colmod.default_layout(CONTESTS["ww-digi"])
    assert "km" not in digi["hidden"] and "mode" not in digi["hidden"]
    assert {"rst_s", "rst_r", "khz"} <= set(digi["hidden"])
    assert colmod.header_label("ex_s", "Zone") == "Zone ges."
    assert colmod.header_label("ex_r", "Nr") == "Nr empf."

    class NewContest:                     # künftiger Contest ohne eigene Vorgabe
        columns = None
    base = colmod.default_layout(NewContest)
    assert [k for k in base["order"] if k not in base["hidden"]] == colmod.DEFAULT_COLUMNS


def test_column_normalize():
    from gogoham import columns as colmod
    from gogoham.contests import CONTESTS
    cls = CONTESTS["cqww-ssb"]
    saved = {"order": ["call", "utc", "bogus"], "hidden": ["utc"], "widths": {"call": 200,
                                                                             "nr": 5}}
    lay = colmod.normalize(saved, cls)
    assert lay["order"][:2] == ["call", "utc"] and "bogus" not in lay["order"]
    assert set(lay["order"]) == set(colmod.COLUMN_KEYS)
    assert lay["widths"]["call"] == 200 and lay["widths"]["nr"] == 50   # 5 ist Unsinn
    assert "utc" in lay["hidden"]
    # nie alles ausblenden
    lay = colmod.normalize({"order": colmod.COLUMN_KEYS, "hidden": colmod.COLUMN_KEYS}, cls)
    assert "call" not in lay["hidden"]


def test_rules_status():
    import datetime as dt
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    import fake_qt
    fake_qt.install()
    from gogoham.gui.dialogs import rules_status
    from gogoham.contests import CONTESTS
    cls = CONTESTS["cqww-ssb"]
    text, old = rules_status(cls, dt.date(2027, 3, 1))
    assert text.startswith("Regeln geprüft: November 2026") and not old
    text, old = rules_status(cls, dt.date(2027, 11, 15))
    assert old and "über ein Jahr" in text
    assert cls.rules_url.startswith("https://www.cqww.com")
