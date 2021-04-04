# Task definitions for invoke
# You must first install invoke, https://www.pyinvoke.org/

# You can also create you own tasks
import sys
from pathlib import Path

from invoke import task
from metapack.appurl import SearchUrl
from metapack_build.tasks.package import build as mp_build

SearchUrl.initialize()  # This makes the 'index:" urls work


from metapack_build.tasks.package import ns

# To configure options for invoke functions you can:
# - Set values in the 'invoke' section of `~/.metapack.yaml
# - Use one of the other invoke config options:
#   http://docs.pyinvoke.org/en/stable/concepts/configuration.html#the-configuration-hierarchy
# - Set the configuration in this file:

# ns.configure(
#    {
#        'metapack':
#            {
#                's3_bucket': 'bucket_name',
#                'wp_site': 'wp sot name',
#                'groups': None,
#                'tags': None
#            }
#    }
# )

# However, the `groups` and `tags` hould really be set in the `metatada.csv`
# file, and `s3_bucket` and `wp_site` should be set at the collection or global level

from pathlib import Path
import metapack as mp

# Finding the package dir is easy for `mp` commands, but
# the easy procedure returns wrong results when using invoke
def get_pkg_dir():

    pkg_dir = Path(__file__).resolve().parent

    if pkg_dir.is_dir():
        return pkg_dir

    if Path.cwd().joinpath('tasks.py').exists():
        return Path.cwd()

    raise Exception("Can't determine package director")


@task(optional=['force'])
def build(c, force=None):
    """Build a filesystem package."""

    sys.path.append(str(Path(__file__).parent.resolve()))
    import pylib

    import logging
    from pylib import logger

    try:
        logging.basicConfig()
        logger.setLevel(logging.INFO)

        pkg_dir = str(get_pkg_dir())

        print(f"Pkg dir: {pkg_dir}")

        pkg = mp.open_package(pkg_dir)

        ex = pylib.ExtractManager(pkg)
        ex.build(force)

        mp_build(c, force)
    finally:
        sys.path.pop() # So other packages won't get this pylib


ns.add_task(build)
