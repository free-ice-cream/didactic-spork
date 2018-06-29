import sys
import time
import ZODB.FileStorage
import ZODB.serialize

filename = sys.argv[1]

print "packing: ", filename
storage=ZODB.FileStorage.FileStorage(filename)
storage.pack(time.time(),ZODB.serialize.referencesf)
print "done"
