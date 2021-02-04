# Task definitions for invoke
# You must first install invoke, https://www.pyinvoke.org/

# You can also create you own tasks
import sys
from pathlib import Path

from invoke import task
from metapack.appurl import SearchUrl
from metapack_build.tasks.package import build as mp_build

SearchUrl.initialize()  # This makes the 'index:" urls work

sys.path.append(str(Path(__file__).parent.resolve()))

import pylib

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


@task(optional=['force'])
def build(c, force=None):
    """Build a filesystem package."""

    import logging
    from pylib import logger
    logging.basicConfig()
    logger.setLevel(logging.INFO)

    pkg_dir = str(Path(__file__).parent.resolve())
    print(f"Pkg dir: {pkg_dir}")

    pkg = mp.open_package(pkg_dir)

    ex = pylib.ExtractManager(pkg)
    ex.build(force)

    mp_build(c, force)


ns.add_task(build)
