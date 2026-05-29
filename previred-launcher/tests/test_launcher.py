import setup


def test_ensure_desktop_shortcut_skips_non_windows(monkeypatch):
    calls = []
    monkeypatch.setattr(setup.sys, "platform", "darwin")
    monkeypatch.setattr(setup.subprocess, "run", lambda *args, **kwargs: calls.append(args))

    setup.ensure_desktop_shortcut()

    assert calls == []


def test_ensure_desktop_shortcut_creates_windows_shortcut(tmp_path, monkeypatch):
    calls = []
    exe = tmp_path / "PreviredDownloader.exe"
    exe.write_text("")
    desktop = tmp_path / "Desktop"
    desktop.mkdir()

    monkeypatch.setattr(setup.sys, "platform", "win32")
    monkeypatch.setattr(setup.sys, "executable", str(exe))
    monkeypatch.setattr(setup.Path, "home", lambda: tmp_path)

    def _fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))

    monkeypatch.setattr(setup.subprocess, "run", _fake_run)

    setup.ensure_desktop_shortcut()

    assert len(calls) == 1
    assert calls[0][0][0] == "powershell"
    assert str(desktop / "Previred Downloader.lnk") in calls[0][0]
    assert str(exe) in calls[0][0]
