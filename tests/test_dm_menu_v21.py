from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from PIL import Image,ImageDraw
import pytest
from modules.ui_nav.coords import load_nav_coords
from modules.ui_nav.menu_labels import play_button,play_page,deathmatch_selected
from modules.dm_runner.team_join import past_team_select_screen
from modules.ui_nav.detectors import detect_state,ScreenState

FIX=Path(__file__).parent/'fixtures/ai_pc/1280x720'

def frame(name):
    im=Image.open(FIX/name).convert('RGB')
    if im.height in (597,598,599,600):im=im.crop((0,24,im.width,im.height))
    return im.resize((1280,720),Image.Resampling.BILINEAR)


@pytest.mark.parametrize('name',['main_menu_play.png','main_menu_play_dm.png','play_dm.png'])
@pytest.mark.parametrize('background',['original','black','white'])
def test_menu_identified_from_bar_without_background(name,background):
    im=frame(name)
    if background!='original':ImageDraw.Draw(im).rectangle((0,40,1279,719),fill=background)
    point=play_button(im)
    assert point is not None and 645<=point[0]<=675 and 14<=point[1]<=26
    coords=load_nav_coords('1280x720')
    assert detect_state(im,ScreenState.MAIN_MENU,coords)
    assert not past_team_select_screen(im,coords)
    assert not detect_state(im,ScreenState.IN_DM,coords)


@pytest.mark.parametrize('name',['team_select.png','team_select_ru_2026-06.png','spawn_invuln_ru_2026-06.png','in_dm_hud.png'])
def test_match_and_team_frames_are_not_menu(name):
    assert play_button(frame(name)) is None


def test_play_and_mode_are_distinct_states():
    assert not play_page(frame('main_menu_play.png'))
    assert play_page(frame('main_menu_play_dm.png'))
    assert deathmatch_selected(frame('main_menu_play_dm.png'))
    im=frame('main_menu_play_dm.png')
    # Inactive mode keeps its word, loses the blue selection highlight.
    patch=im.crop((618,80,698,101)).convert('L').convert('RGB');im.paste(patch,(618,80))
    assert play_page(im) and not deathmatch_selected(im)


def navigator():
    from modules.dm_runner.navigate import DmNavigator
    n=DmNavigator.__new__(DmNavigator)
    n.coords=load_nav_coords('1280x720');n.artifacts=Mock();n._abort_if_stopped=Mock();n._nav_progress=Mock()
    return n


def test_click_uses_detected_play_and_checks_transition(monkeypatch):
    from modules.dm_runner import navigate
    n=navigator();im=frame('main_menu_play.png');ImageDraw.Draw(im).rectangle((0,40,1279,719),fill='black')
    n.driver=SimpleNamespace(capture=Mock(side_effect=[im,im,frame('main_menu_play_dm.png')]),click=Mock(),sim=False)
    monkeypatch.setattr(navigate.time,'sleep',lambda _:None)
    n._click_target('main_menu_play')
    pt=n.driver.click.call_args.args[0]
    assert 645<=pt.x<=675 and 14<=pt.y<=26


def test_no_search_before_deathmatch_selected(monkeypatch):
    from modules.ui_nav.errors import UiNavError
    n=navigator();im=frame('main_menu_play.png')
    n.driver=SimpleNamespace(capture=lambda:im,click=Mock(),sim=False)
    with pytest.raises(UiNavError,match='selection not confirmed'):n._click_target('start_search')
    n.driver.click.assert_not_called()


def test_failed_menu_detection_never_sends_console_commands(monkeypatch):
    from modules.ui_nav import cs2_console
    from modules.ui_nav.errors import UiNavTimeoutError
    n=navigator();n._search_requested=False;n.driver=SimpleNamespace(capture=lambda:Image.new('RGB',(1280,720)),sim=False)
    n._set_sim_phase=Mock();n.wait_main_menu=Mock(side_effect=UiNavTimeoutError('menu'))
    send=Mock();monkeypatch.setattr(cs2_console,'run_cs2_console_commands',send)
    with pytest.raises(UiNavTimeoutError):n._reset_search()
    send.assert_not_called()


def test_disabled_background_is_not_an_empty_capture():
    from modules.ui_nav.capture import is_suspect_black_capture
    im=frame('main_menu_play.png');ImageDraw.Draw(im).rectangle((0,40,1279,719),fill='black')
    assert not is_suspect_black_capture(im)
    assert is_suspect_black_capture(Image.new('RGB',(1280,720),'black'))


def test_disguised_spawn_probe_matches_cannot_buy_in_menu():
    coords=load_nav_coords('1280x720');im=frame('main_menu_play.png');d=ImageDraw.Draw(im)
    for p in coords.probes('spawn_invuln')+coords.probes('in_dm'):
        d.point((p.x,p.y),fill=p.rgb)
    assert not past_team_select_screen(im,coords)


def test_failed_start_click_is_not_reported_as_search(monkeypatch):
    from modules.dm_runner import navigate
    from modules.ui_nav.errors import UiNavError
    n=navigator();im=frame('main_menu_play_dm.png')
    n.driver=SimpleNamespace(capture=lambda:im,click=Mock(),sim=False)
    monkeypatch.setattr(navigate.time,'sleep',lambda _:None)
    with pytest.raises(UiNavError,match='did not take effect'):n._click_target('start_search')
    assert n.driver.click.call_count==2
