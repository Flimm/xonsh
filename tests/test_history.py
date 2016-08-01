# -*- coding: utf-8 -*-
"""Tests the xonsh history."""
# pylint: disable=protected-access
import io
import os
import sys
import shlex

from xonsh.lazyjson import LazyJSON
from xonsh.history import History, _hist_create_parser, _hist_parse_args
from xonsh import history

import pytest


@pytest.yield_fixture
def hist():
    h = History(filename='xonsh-HISTORY-TEST.json', here='yup', sessionid='SESSIONID', gc=False)
    yield h
    os.remove(h.filename)


def test_hist_init(hist):
    """Test initialization of the shell history."""
    with LazyJSON(hist.filename) as lj:
        obs = lj['here']
    assert 'yup' == obs


def test_hist_append(hist, xonsh_builtins):
    """Verify appending to the history works."""
    xonsh_builtins.__xonsh_env__['HISTCONTROL'] = set()
    hf = hist.append({'joco': 'still alive'})
    assert hf is None
    assert 'still alive' == hist.buffer[0]['joco']


def test_hist_flush(hist, xonsh_builtins):
    """Verify explicit flushing of the history works."""
    hf = hist.flush()
    assert hf is None
    xonsh_builtins.__xonsh_env__['HISTCONTROL'] = set()
    hist.append({'joco': 'still alive'})
    hf = hist.flush()
    assert hf is not None
    while hf.is_alive():
        pass
    with LazyJSON(hist.filename) as lj:
        obs = lj['cmds'][0]['joco']
    assert 'still alive' == obs


def test_cmd_field(hist, xonsh_builtins):
    # in-memory
    xonsh_builtins.__xonsh_env__['HISTCONTROL'] = set()
    hf = hist.append({'rtn': 1})
    assert hf is None
    assert 1 == hist.rtns[0]
    assert 1 == hist.rtns[-1]
    assert None == hist.outs[-1]
    # slice
    assert [1] == hist.rtns[:]
    # on disk
    hf = hist.flush()
    assert hf is not None
    assert 1 == hist.rtns[0]
    assert 1 == hist.rtns[-1]
    assert None == hist.outs[-1]


cmds = ['ls', 'cat hello kitty', 'abc', 'def', 'touch me', 'grep from me']

@pytest.mark.parametrize('inp, commands, offset', [
    ('', cmds, (0, 1)),
    ('-r', list(reversed(cmds)), (len(cmds)- 1, -1)),
    ('0', cmds[0:1], (0, 1)),
    ('1', cmds[1:2], (1, 1)),
    ('-2', cmds[-2:-1], (len(cmds) -2 , 1)),
    ('1:3', cmds[1:3], (1, 1)),
    ('1::2', cmds[1::2], (1, 2)),
    ('-4:-2', cmds[-4:-2], (len(cmds) - 4, 1))
    ])
def test_show_cmd_numerate(inp, commands, offset, hist, xonsh_builtins, capsys):
    """Verify that CLI history commands work."""
    base_idx, step = offset
    xonsh_builtins.__xonsh_history__ = hist
    xonsh_builtins.__xonsh_env__['HISTCONTROL'] = set()
    for ts,cmd in enumerate(cmds):  # populate the shell history
        hist.append({'inp': cmd, 'rtn': 0, 'ts':(ts+1, ts+1.5)})

    exp = ('{}: {}'.format(base_idx + idx * step, cmd)
           for idx, cmd in enumerate(list(commands)))
    exp = '\n'.join(exp)

    history.history_main(['show', '-n'] + shlex.split(inp))
    out, err = capsys.readouterr()
    assert out.rstrip() == exp


def test_histcontrol(hist, xonsh_builtins):
    """Test HISTCONTROL=ignoredups,ignoreerr"""

    xonsh_builtins.__xonsh_env__['HISTCONTROL'] = 'ignoredups,ignoreerr'
    assert len(hist.buffer) == 0

    # An error, buffer remains empty
    hist.append({'inp': 'ls foo', 'rtn': 2})
    assert len(hist.buffer) == 0

    # Success
    hist.append({'inp': 'ls foobazz', 'rtn': 0})
    assert len(hist.buffer) == 1
    assert 'ls foobazz' == hist.buffer[-1]['inp']
    assert 0 == hist.buffer[-1]['rtn']

    # Error
    hist.append({'inp': 'ls foo', 'rtn': 2})
    assert len(hist.buffer) == 1
    assert 'ls foobazz' == hist.buffer[-1]['inp']
    assert 0 == hist.buffer[-1]['rtn']

    # File now exists, success
    hist.append({'inp': 'ls foo', 'rtn': 0})
    assert len(hist.buffer) == 2
    assert 'ls foo' == hist.buffer[-1]['inp']
    assert 0 == hist.buffer[-1]['rtn']

    # Success
    hist.append({'inp': 'ls', 'rtn': 0})
    assert len(hist.buffer) == 3
    assert 'ls' == hist.buffer[-1]['inp']
    assert 0 == hist.buffer[-1]['rtn']

    # Dup
    hist.append({'inp': 'ls', 'rtn': 0})
    assert len(hist.buffer) == 3

    # Success
    hist.append({'inp': '/bin/ls', 'rtn': 0})
    assert len(hist.buffer) == 4
    assert '/bin/ls' == hist.buffer[-1]['inp']
    assert 0 == hist.buffer[-1]['rtn']

    # Error
    hist.append({'inp': 'ls bazz', 'rtn': 1})
    assert len(hist.buffer) == 4
    assert '/bin/ls' == hist.buffer[-1]['inp']
    assert 0 == hist.buffer[-1]['rtn']

    # Error
    hist.append({'inp': 'ls bazz', 'rtn': -1})
    assert len(hist.buffer) == 4
    assert '/bin/ls' == hist.buffer[-1]['inp']
    assert 0 == hist.buffer[-1]['rtn']


@pytest.mark.parametrize('args', [ '-h', '--help', 'show -h', 'show --help'])
def test_parse_args_help(args, capsys):
    with pytest.raises(SystemExit):
        args = _hist_parse_args(shlex.split(args))
    assert 'show this help message and exit' in capsys.readouterr()[0]


@pytest.mark.parametrize('args, exp', [
    ('', ('show', 'session', [], False, False)),
    ('1:5', ('show', 'session', ['1:5'], False, False)),
    ('show', ('show', 'session', [], False, False)),
    ('show 15', ('show', 'session', ['15'], False, False)),
    ('show bash 3:5 15:66', ('show', 'bash', ['3:5', '15:66'], False, False)),
    ('show -r', ('show', 'session', [], False, True)),
    ('show -rn bash', ('show', 'bash', [], True, True)),
    ('show -n -r -30:20', ('show', 'session', ['-30:20'], True, True)),
    ('show -n zsh 1:2:3', ('show', 'zsh', ['1:2:3'], True, False))
    ])
def test_parser_show(args, exp):
    # use dict instead of argparse.Namespace for pretty pytest diff
    exp_ns = {'action': exp[0],
              'session': exp[1],
              'slices': exp[2],
              'numerate': exp[3],
              'reverse': exp[4],
              'start_time': None,
              'end_time': None}
    ns = _hist_parse_args(shlex.split(args))
    assert ns.__dict__ == exp_ns
