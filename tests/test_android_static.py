"""The Android app cannot be compiled where most of the work is done (no SDK), so this file checks the contracts between its parts by
reading them: the page and the Kotlin bridge agree on names, the manifest declares what the code uses, every resource that the code
names exists, and the way back and the player's notification are wired. It is not a substitute for building the app and trying it on
a phone, but a renamed method or a forgotten permission no longer waits for that to be found."""
import os
import re
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "android", "app", "src", "main")
KOTLIN = os.path.join(APP, "java", "app", "burdamix")
WEB = os.path.join(ROOT, "gui", "web")
ANDROID_NS = "{http://schemas.android.com/apk/res/android}"


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


def manifest():
    return ET.parse(os.path.join(APP, "AndroidManifest.xml")).getroot()


def test_the_manifest_declares_the_player_service_as_media_playback_and_the_permissions_it_needs():
    root = manifest()
    permissions = {p.get(ANDROID_NS + "name") for p in root.findall("uses-permission")}
    assert {"android.permission.FOREGROUND_SERVICE", "android.permission.FOREGROUND_SERVICE_MEDIA_PLAYBACK",
            "android.permission.POST_NOTIFICATIONS", "android.permission.WAKE_LOCK"} <= permissions
    service = next(s for s in root.iter("service") if s.get(ANDROID_NS + "name") == ".PlaybackService")
    assert service.get(ANDROID_NS + "foregroundServiceType") == "mediaPlayback" and service.get(ANDROID_NS + "exported") == "false"
    assert os.path.isfile(os.path.join(KOTLIN, "PlaybackService.kt"))


def test_the_notification_brings_back_the_running_app_instead_of_starting_a_second_python():
    activity = next(a for a in manifest().iter("activity") if a.get(ANDROID_NS + "name") == ".WebActivity")
    assert activity.get(ANDROID_NS + "launchMode") == "singleTask"


def test_the_file_provider_matches_what_the_code_and_the_share_folder_expect():
    provider = next(p for p in manifest().iter("provider"))
    assert provider.get(ANDROID_NS + "authorities") == "${applicationId}.fileprovider" and provider.get(ANDROID_NS + "exported") == "false"
    assert '"${context.packageName}.fileprovider"' in read(KOTLIN, "Platform.kt")
    paths = ET.parse(os.path.join(APP, "res", "xml", "file_paths.xml")).getroot()
    cache = paths.find("cache-path")
    assert cache.get("path") == "share/"
    # the three places that name the folder: where Python writes (cacheDir/share), what the provider shares, what Platform allows
    assert 'cacheDir.resolve("share")' in read(KOTLIN, "WebActivity.kt") and 'File(context.cacheDir, "share")' in read(KOTLIN, "Platform.kt")


def test_every_method_the_page_calls_on_the_bridge_exists_in_kotlin():
    kotlin = read(KOTLIN, "WebActivity.kt")
    exposed = set(re.findall(r"@JavascriptInterface\s+fun (\w+)", kotlin))
    used = set()
    for name in os.listdir(WEB):
        if name.endswith(".js"):
            text = read(WEB, name)
            used |= set(re.findall(r"BurdamixAndroid\.(\w+)", text)) | set(re.findall(r"\bhost\.(\w+)\(", text) if name in ("android.js", "androidmedia.js") else [])
    assert used and used <= exposed | {"methods", "call"}, used - exposed


def test_the_words_kotlin_sends_to_the_page_are_understood_by_the_page():
    page = read(WEB, "androidmedia.js")
    service = read(KOTLIN, "PlaybackService.kt")
    for word in re.findall(r'act\("([a-z]+)', service):
        assert f'"{word}"' in page or f'"{word}:"' in page, word       # "seek:<ms>" carries a number after the colon
    assert "window.__burdamixMedia" in read(KOTLIN, "WebActivity.kt") and "window.burdamixBack" in read(KOTLIN, "WebActivity.kt")
    assert "window.burdamixBack = back" in read(WEB, "mobile.js")


def test_the_page_sends_the_player_state_that_the_service_reads():
    sent = set(re.findall(r"\b(has|title|artist|album|cover|playing|position|duration|shuffle):", read(WEB, "androidmedia.js")))
    read_by_service = set(re.findall(r'opt\w+\("(\w+)"', read(KOTLIN, "PlaybackService.kt")))
    assert read_by_service <= sent, read_by_service - sent
    assert "window.__nativeMedia" in read(WEB, "player.js")


def test_every_drawable_and_resource_the_code_names_exists_and_is_valid_xml():
    named = set()
    for name in ("PlaybackService.kt", "WebActivity.kt", "Platform.kt"):
        named |= set(re.findall(r"R\.drawable\.(\w+)", read(KOTLIN, name)))
    assert {"ic_stat_burdamix", "ic_previous", "ic_next", "ic_play", "ic_pause", "ic_shuffle"} <= named
    for drawable in named:
        path = os.path.join(APP, "res", "drawable", drawable + ".xml")
        assert os.path.isfile(path), drawable
        assert ET.parse(path).getroot().tag == "vector"


def test_the_python_host_takes_the_share_folder_the_activity_passes():
    import ast
    tree = ast.parse(read(APP, "python", "burdamix_host.py"))
    params = [a.arg for a in next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "start").args.args]
    call = re.search(r'host\.callAttr\("start",(.*?)\)\n', read(KOTLIN, "WebActivity.kt"), re.S).group(1)
    assert len([a for a in re.split(r",\s*(?![^(]*\))", call.replace("\n", " ")) if a.strip()]) == len(params)


def test_the_back_gesture_leaves_the_music_playing_and_only_closes_the_app_when_nothing_plays():
    kotlin = read(KOTLIN, "WebActivity.kt")
    assert "moveTaskToBack(true)" in kotlin and "finish()" in kotlin and "PlaybackService.playing" in kotlin
    assert "enableOnBackInvokedCallback" in read(APP, "AndroidManifest.xml")      # targetSdk 34 still calls onBackPressed; keep it explicit
