"""Isola os testes do usuário real: config e estado vão para um diretório temporário."""

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="maverick-tests-")
os.environ["XDG_CONFIG_HOME"] = os.path.join(_tmp, "config")
os.environ["XDG_DATA_HOME"] = os.path.join(_tmp, "data")
