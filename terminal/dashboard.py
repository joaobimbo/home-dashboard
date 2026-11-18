#!/usr/bin/env python3
"""Keyboard dashboard for the local console; all device access goes via Flask."""
import curses
import json
import os
import subprocess
import http.cookiejar
import textwrap
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = 'http://127.0.0.1:5000'
TABS = ('Música', 'AC', 'Luzes', 'Estores', 'Agente')
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def api(path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(BASE + path, data=data, headers={'Content-Type': 'application/json'})
    try:
        with OPENER.open(req, timeout=100) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            return json.load(exc)
        except ValueError:
            return {'ok': False, 'error': str(exc)}


def main(screen):
    curses.curs_set(0)
    screen.timeout(200)
    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)
        curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_CYAN)
        curses.init_pair(3, curses.COLOR_GREEN, -1)
        curses.init_pair(4, curses.COLOR_YELLOW, -1)
    tab, selected, message = 0, 0, 'A ligar ao dashboard…'
    items, states, music = [], {}, {}
    results = queue.Queue()
    loading = False
    agent_text = 'Enter: escrever um pedido ao assistente.'
    agent_token = None
    agent_busy = False
    music_results = []
    music_outputs = []
    music_view = 'results'
    music_index = 0
    music_output = None
    transfer_target = {}
    music_notice = 'S: pesquisar   D: escolher saída'
    last_refresh = 0
    def job(kind, fn):
        def run():
            try:
                results.put((kind, fn(), None))
            except Exception as exc:
                results.put((kind, None, str(exc)))
        threading.Thread(target=run, daemon=True).start()
    def refresh():
        nonlocal loading, last_refresh
        if loading:
            return
        loading = True
        last_refresh = time.monotonic()
        def load():
            devices = api('/api/shelly/devices')
            ac = api('/api/daikin/devices')
            statuses = {}
            for device in ac:
                statuses[device['id']] = api('/api/daikin/' + urllib.parse.quote(device['id'], safe='') + '/status')
            return devices, ac, statuses, api('/api/spotify/status')
        job('refresh', load)
    def post(path, payload):
        nonlocal message
        message = 'A executar…'
        job('command', lambda: api(path, payload))
    def draw(y, x, text, attr=0):
        h, w = screen.getmaxyx()
        if y < h and x < w:
            try: screen.addnstr(y, x, str(text), max(0, w-x-1), attr)
            except curses.error: pass
    refresh()
    while True:
        try:
            while True:
                kind, data, error = results.get_nowait()
                if kind == 'refresh':
                    loading = False
                    if error: message = 'Sem ligação: ' + error
                    else:
                        devices, ac, states, music = data
                        items = [[], ac, [d for d in devices if d.get('component') != 'cover'], [d for d in devices if d.get('component') == 'cover']]
                        message = 'Atualizado às ' + time.strftime('%H:%M:%S')
                elif kind in ('music_search', 'music_outputs'):
                    if error or not data or not data.get('ok'):
                        music_notice = 'Erro: ' + (error or (data or {}).get('error', 'Spotify indisponível'))
                    elif kind == 'music_search':
                        music_results = data.get('results', [])
                        music_view = 'results'
                        music_index = 0
                        music_notice = 'Enter: reproduzir' if music_results else 'Sem resultados.'
                    else:
                        music_outputs = data.get('devices', [])
                        music_view = 'outputs'
                        music_index = 0
                        music_notice = 'Enter: escolher saída' if music_outputs else 'Nenhuma saída disponível.'
                elif kind == 'music_transfer':
                    if error or not data or not data.get('ok'):
                        music_notice = 'Erro: ' + (error or (data or {}).get('error', 'Transferência falhou'))
                    else:
                        music_output = transfer_target.get('id')
                        music_notice = 'Saída selecionada: ' + transfer_target.get('name', '')
                        last_refresh = 0
                elif kind == 'agent':
                    agent_busy = False
                    if error:
                        agent_text = 'Erro: ' + error
                    elif not data or not data.get('ok'):
                        agent_text = (data or {}).get('error', 'Não foi possível contactar o assistente.')
                    else:
                        agent_text = data.get('message') or 'Concluído.'
                        agent_token = data.get('token') if data.get('kind') == 'automation_confirmation' else None
                else:
                    message = ('Erro: ' + error) if error else (('Erro: ' + str(data.get('error', 'falhou'))) if isinstance(data, dict) and not data.get('ok', True) else 'Comando enviado')
                    last_refresh = 0
        except queue.Empty: pass
        if time.monotonic() - last_refresh > 30: refresh()
        rows = items[tab] if items and tab < len(items) else []
        selected = max(0, min(selected, len(rows)-1))
        screen.erase()
        draw(1, 2, 'NOSSA CASINHA', curses.color_pair(1) | curses.A_BOLD)
        draw(2, 2, 'Painel local  ·  ' + time.strftime('%H:%M'), curses.A_DIM)
        x = 2
        for i, title in enumerate(TABS):
            label = '  ' + title + '  '
            draw(4, x, label, curses.color_pair(2) if tab == i else curses.color_pair(1))
            x += len(label) + 1
        if tab == 0:
            track = music.get('track') or {}
            draw(6, 3, track.get('name') or 'Sem reprodução ativa', curses.A_BOLD)
            draw(7, 3, ', '.join(track.get('artists') or []))
            active = music.get('device') or {}
            chosen = next((d for d in music_outputs if d.get('id') == music_output), None)
            draw(8, 3, 'Saída: ' + ((chosen or active).get('name') or 'não selecionada'), curses.color_pair(1))
            draw(10, 3, 'SAÍDAS' if music_view == 'outputs' else 'PESQUISA', curses.A_BOLD)
            music_rows = music_outputs if music_view == 'outputs' else music_results
            h, w = screen.getmaxyx()
            visible = max(1, h - 16)
            offset = max(0, music_index - visible + 1)
            for n, item in enumerate(music_rows[offset:offset+visible], offset):
                label = item.get('name', '?') + (' · ' + item.get('subtitle', '') if music_view == 'results' else (' (ativa)' if item.get('is_active') else ''))
                draw(11+n-offset, 3, ('› ' if n == music_index else '  ') + label, curses.color_pair(2) if n == music_index else 0)
            draw(h-5, 2, music_notice, curses.A_DIM)
            draw(h-4, 2, 'S pesquisar  D saídas  Enter escolher  Espaço/N/P', curses.A_DIM)
        elif tab == 4:
            h, w = screen.getmaxyx()
            draw(7, 3, 'ASSISTENTE', curses.color_pair(1) | curses.A_BOLD)
            for row, line in enumerate(textwrap.wrap(agent_text, width=max(10, w-7), replace_whitespace=False)[:max(1, h-13)]):
                draw(9+row, 3, line)
            if agent_token:
                draw(h-5, 2, 'C: confirmar automação    X: cancelar', curses.color_pair(4))
            else:
                draw(h-5, 2, 'Enter: escrever pedido', curses.A_DIM)
        else:
            h, w = screen.getmaxyx()
            visible = max(1, h - 13)
            offset = max(0, selected - visible + 1)
            for n, device in enumerate(rows[offset:offset+visible], offset):
                status = states.get(device.get('id'), {}) if tab == 1 else device
                title = device.get('display_name') or device.get('name') or device.get('id', '?')
                room = device.get('room', '')
                if tab == 1:
                    detail = ('Ligado' if status.get('power') else 'Desligado') if status.get('ok') else 'indisponível'
                    if status.get('ok'): detail += '   %s°C  ·  %s' % (status.get('setpoint', '--'), status.get('mode', '--'))
                else:
                    detail = str(device.get('state', device.get('status', '')))
                    if isinstance(device.get('state'), dict): detail = str(device['state'].get('state', ''))
                    if isinstance(device.get('brightness'), (int, float)): detail += '  %s%%' % device['brightness']
                draw(7+n-offset, 3, ('› ' if n == selected else '  ') + title + '   ' + room + '   ' + detail, curses.color_pair(2) if n == selected else 0)
            if not rows: draw(7, 4, 'Sem dispositivos disponíveis.')
            draw(max(8, h-5), 2, ('Enter: ligar  +/-: temperatura  M: modo  F: ventoinha' if tab == 1 else ('Enter: ligar  B: brilho %%  +/-: brilho' if tab == 2 else 'Enter: abrir  F: fechar  S: parar')), curses.A_DIM)
        h, w = screen.getmaxyx()
        draw(h-3, 2, message, curses.color_pair(4))
        draw(h-2, 2, '← → separadores   ↑ ↓ selecionar   R atualizar   Q sair', curses.A_DIM)
        screen.refresh()
        key = screen.getch()
        if key != -1 and os.environ.get('TERM') == 'linux':
            # The web screen-off action uses force blanking, which stays blank
            # until explicitly poked even when the console receives input.
            try:
                subprocess.run(['/usr/bin/setterm', '--term', 'linux', '--blank', 'poke'],
                               stderr=subprocess.DEVNULL,
                               timeout=1, check=False)
            except (OSError, subprocess.TimeoutExpired):
                pass
        if key in (ord('q'), ord('Q')): break
        if key in (curses.KEY_LEFT, ord('h')): tab = (tab-1)%len(TABS); selected = 0
        elif key in (curses.KEY_RIGHT, ord('l'), 9): tab = (tab+1)%len(TABS); selected = 0
        elif key in (curses.KEY_UP, ord('k')):
            if tab == 0: music_index = max(0, music_index-1)
            else: selected = max(0, selected-1)
        elif key in (curses.KEY_DOWN, ord('j')):
            if tab == 0: music_index = max(0, min(len(music_outputs if music_view == 'outputs' else music_results)-1, music_index+1))
            else: selected = min(len(rows)-1, selected+1)
        elif key in (ord('r'), ord('R')): refresh()
        elif tab == 4 and not agent_busy:
            if key in (10, 13, curses.KEY_ENTER):
                h, w = screen.getmaxyx()
                draw(h-4, 2, 'Pedido: ' + ' '*max(0, w-12))
                curses.echo()
                curses.curs_set(1)
                screen.timeout(-1)
                try:
                    raw = screen.getstr(h-4, min(10, w-2), max(1, min(500, w-12)))
                    prompt = raw.decode('utf-8', 'replace').strip()
                finally:
                    curses.noecho()
                    curses.curs_set(0)
                    screen.timeout(200)
                if prompt:
                    agent_token = None
                    agent_text = 'A interpretar o pedido…'
                    agent_busy = True
                    job('agent', lambda prompt=prompt: api('/api/agent/request', {'message': prompt}))
            elif key == ord('c') and agent_token:
                token = agent_token
                agent_token = None
                agent_busy = True
                agent_text = 'A guardar automação…'
                job('agent', lambda token=token: api('/api/agent/confirm', {'token': token}))
            elif key == ord('x') and agent_token:
                agent_token = None
                agent_text = 'Automação cancelada.'
        elif tab == 0:
            if key == ord('s'):
                h, w = screen.getmaxyx()
                draw(h-4, 2, 'Pesquisar: ' + ' '*max(0, w-15))
                curses.echo(); curses.curs_set(1); screen.timeout(-1)
                try:
                    query = screen.getstr(h-4, min(13, w-2), max(1, min(250, w-15))).decode('utf-8', 'replace').strip()
                finally:
                    curses.noecho(); curses.curs_set(0); screen.timeout(200)
                if query:
                    music_notice = 'A pesquisar…'
                    job('music_search', lambda query=query: api('/api/spotify/search?q=' + urllib.parse.quote(query)))
            elif key == ord('d'):
                music_notice = 'A procurar saídas…'
                job('music_outputs', lambda: api('/api/spotify/devices'))
            elif key in (10, 13, curses.KEY_ENTER):
                music_rows = music_outputs if music_view == 'outputs' else music_results
                if music_rows:
                    item = music_rows[music_index]
                    if music_view == 'outputs':
                        if item.get('is_restricted'):
                            music_notice = 'Esta saída não permite controlo.'
                        else:
                            transfer_target = item
                            music_notice = 'A mudar de saída…'
                            job('music_transfer', lambda ident=item['id']: api('/api/spotify/device', {'device_id': ident}))
                    else:
                        post('/api/spotify/play-uri', {'uri': item['uri'], 'device_id': music_output})
            elif key in (32, ord('n'), ord('p')):
                command = ('pause' if music.get('is_playing') else 'play') if key == 32 else ('next' if key == ord('n') else 'previous')
                post('/api/spotify/' + command, {'device_id': music_output})
        elif rows:
            device = rows[selected]; ident = urllib.parse.quote(device['id'], safe='')
            if tab == 1:
                status = states.get(device['id'], {})
                base = '/api/daikin/' + ident
                if key in (10, 13, curses.KEY_ENTER) and status.get('ok'): post(base+'/power', {'state': 'off' if status.get('power') else 'on'})
                elif key in (ord('+'), ord('-')) and status.get('ok'):
                    value = max(10, min(32, int(status.get('setpoint', 22)) + (1 if key == ord('+') else -1)))
                    post(base+'/setpoint', {'temperature': value})
                elif key in (ord('m'), ord('f')) and status.get('ok'):
                    choices = ['auto','cool','heat','dry','fan'] if key == ord('m') else ['auto','low','mid','high']
                    field = 'mode' if key == ord('m') else 'fan_speed'
                    current = status.get(field)
                    value = choices[(choices.index(current)+1)%len(choices)] if current in choices else choices[0]
                    post(base+('/mode' if key == ord('m') else '/fan'), {('mode' if key == ord('m') else 'speed'): value})
            elif tab == 3 and key in (10, 13, curses.KEY_ENTER, ord('f'), ord('s')):
                post('/api/shelly/'+ident+'/cover_action', {'command': 'close' if key == ord('f') else ('stop' if key == ord('s') else 'open')})
            elif tab == 2 and key in (ord('b'), ord('+'), ord('-')) and device.get('component') in ('light', 'rgbcct'):
                current = device.get('brightness') or 50
                if key == ord('b'):
                    h, w = screen.getmaxyx()
                    draw(h-3, 2, 'Brilho (1-100): ' + ' '*12)
                    screen.move(h-3, min(18, w-2))
                    curses.echo()
                    curses.curs_set(1)
                    screen.timeout(-1)
                    try:
                        raw = screen.getstr(h-3, min(18, w-2), 3).decode('ascii', 'ignore')
                        value = int(raw)
                    except ValueError:
                        value = 0
                    finally:
                        curses.noecho()
                        curses.curs_set(0)
                        screen.timeout(200)
                else:
                    value = max(1, min(100, int(current) + (5 if key == ord('+') else -5)))
                if 1 <= value <= 100:
                    post('/api/shelly/'+ident+('/rgbcct' if device.get('component') == 'rgbcct' else '/light_level'), {'brightness': value})
                else:
                    message = 'Introduza um valor entre 1 e 100.'
            elif tab == 2 and key in (10, 13, curses.KEY_ENTER):
                post('/api/shelly/'+ident+'/action', {'action': 'toggle'})


if __name__ == '__main__':
    curses.wrapper(main)
