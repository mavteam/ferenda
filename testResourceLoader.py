import tempfile
import shutil

from ferenda.compat import unittest

# SUT
from ferenda import ResourceLoader

# this class mainly exists so that we can try out make_loadpath
class SubTestCase(unittest.TestCase):
    pass


def testResourceLoader(SubTestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp()
        loadpath = [self.tempdir + "/primary", self.tempdir + "/secondary"]
        util.writefile(loadpath[0]+os.sep+"primaryresource.txt", "Hello")
        util.writefile(loadpath[1]+os.sep+"secondaryresource.txt", "World")
        self.resourceloader = ResourceLoader(*loadpath)
    
    def tearDown(self):
        shutil.removedir(self.tempdir)  
    
    def test_loadpath(self):
        self.assertEqual(ResourceLoader.make_loadpath(self),
                         ["test/res",  # from test.testResourceLoader.SubTestCase
                          "ferenda/res" # from ferenda.compat.unittest.TestCase
                          ]
                          
    def test_exists(self):
        self.assertTrue(self.resourceloader.exists("primaryresource.txt"))
        self.assertTrue(self.resourceloader.exists("secondaryresource.txt"))
        self.assertTrue(self.resourceloader.exists("robots.txt"))
        self.assertFalse(self.resourceloader.exists("nonexistent.txt"))

    def test_open(self):
        with self.resourceloader.open("primaryresource.txt") as fp:
            self.assertEqual("Hello", fp.read())    
        with self.resourceloader.open("secondaryresource.txt") as fp:
            self.assertEqual("World", fp.read())
        with self.assertRaises(ResourceNotFound):
            fp = self.resourceloader.open("nonexistent.txt")
        with self.resourceloader.open("robots.txt") as fp:  # should be available through the pkg_resources API
            self.assertStartswith(fp.read(), "# robotstxt.org/")
            
    def test_read(self):
        self.assertEqual("Hello", self.resourceloader.read("primaryresource.txt"))
        self.assertEqual("World", self.resourceloader.read("secondaryresource.txt"))
        self.assertStartsWith(self.resourceloader.read("robots.txt"), "# robotstxt.org/")
        with self.assertRaises(ResourceNotFound):
            self.resourceloader.read("nonexistent.txt"))
            
    def test_filename(self):
        self.assertEqual(self.tempdir + "/primary/primaryresource.txt", self.resourceloader.filename("primaryresource.txt"))
        self.assertEqual(self.tempdir + "/secondary/secondaryresource.txt", self.resourceloader.filename("secondaryresource.txt"))
        self.assertEqual("ferenda/res/robots.txt", self.resourceloader.filename("robots.txt"))
        with self.assertRaises(ResourceNotFound):
            self.resourceloader.filename("nonexistent.txt"))
    