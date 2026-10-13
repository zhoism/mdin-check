from mdin_check.namelist import parse


def test_comment_with_slash_does_not_end_the_group():
    md = parse("t\n&cntrl\n dt=0.002, ! 2 fs/step\n cut=15.0,\n/\n")
    assert md.first("cntrl").value("cut") == 15.0


def test_last_value_wins():
    md = parse("t\n&cntrl\n dt=0.004, dt=0.002,\n/\n")
    assert md.first("cntrl").value("dt") == 0.002


def test_terminators():
    for end in ("/", "&end", "$end", "&END"):
        md = parse(f"t\n&cntrl\n imin=1,\n{end}\n&ewald\n skinnb=1.0,\n/\n")
        assert md.first("cntrl").terminator == end.lower()
        assert md.first("ewald").value("skinnb") == 1.0


def test_quoted_strings_and_doubled_quotes():
    md = parse("t\n&cntrl\n restraintmask=':1-10@C1''', bellymask=\":1/2\",\n/\n")
    nl = md.first("cntrl")
    assert nl.value("restraintmask") == ":1-10@C1'"
    assert nl.value("bellymask") == ":1/2"


def test_d_exponent_and_logicals():
    nl = parse("t\n&cntrl\n dt=2.0d-3, x=.true., y=F,\n/\n").first("cntrl")
    assert nl.value("dt") == 0.002 and nl.value("x") is True and nl.value("y") is False


def test_hidden_namelist():
    md = parse("t\n&cntrl\n imin=1,\n/\n\t&ewald\n skinnb=1,\n/\n")
    assert md.first("ewald") is None
    assert any(i.code == "HIDDEN_NAMELIST" for i in md.issues)


def test_unclosed_quote():
    md = parse("t\n&cntrl\n restraintmask=':1-10,\n/\n")
    assert any(i.code == "UNCLOSED_QUOTE" for i in md.issues)


def test_wt_blocks_and_trailing_lines():
    md = parse("t\n&cntrl\n nmropt=1,\n/\n&wt type='TEMP0', istep2=10 /\n&wt type='END' /\nDISANG=rst.dat\n")
    assert [b.value("type") for b in md.all("wt")] == ["TEMP0", "END"]
    assert md.other_lines == [(7, "DISANG=rst.dat")]
