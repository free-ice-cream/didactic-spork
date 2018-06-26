import sys
sys.path.insert(0, '/home/hivemind/didactic-spork')

activate_this = '/home/hivemind/didactic-spork/bin/activate_this.py'
execfile(activate_this, dict(__file__=activate_this))

from gameserver.main import app as application
