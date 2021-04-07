"""


"""

from pathlib import Path

from demosearch import FileCache
from tqdm.notebook import tqdm

tqdm.pandas()

import pandas as pd

from geoid.censusnames import stusab
import libgeohash as gh
import rowgenerators as rg
from shapely.geometry import Polygon
import geopandas as gpd
from tqdm.notebook import tqdm

tqdm.pandas()

import logging

logger = logging.getLogger(__name__)

import warnings
# For:
# WARNING:fiona._env:Recode from CP437 to UTF-8 failed with the error: "Invalid argument".
warnings.filterwarnings('ignore')

# From https://gis.stackexchange.com/a/269552
def convert_wgs_to_utm(lat, lon):
    import math
    utm_band = str((math.floor((lon + 180) / 6) % 60) + 1)
    if len(utm_band) == 1:
        utm_band = '0' + utm_band
    if lat >= 0:
        epsg_code = '326' + utm_band
    else:
        epsg_code = '327' + utm_band
    return epsg_code  # ,  CRS.from_epsg(epsg_code), utm.from_latlon(lat, lon)


def geohash_to_polygons(ghashes):
    """
    Converts a list of geohashes to a shapely polygon.
    """
    polygons = []
    for ghash in ghashes:
        # bbox returns a tuple of lat, lon pairs which essentially is (y, x) in cartesian plane.
        # Converting it into (x, y) before passing to shapely.
        bounds = [ele[::-1] for ele in gh.bbox(ghash, coordinates=True)]
        polygons.append(Polygon(bounds))

    return polygons


class PkgError(Exception):
    pass


class ExtractManager(object):

    def __init__(self, pkg):
        self.pkg = pkg

        self.pkg_root = Path(self.pkg.path).parent

        self.cache = FileCache(self.pkg_root.joinpath('data', 'cache'))

        # self.cp = CensusProcessor(self.cache, 2019, progress_bar=True)
        # self.tp = TractProcessor(self.cache)

        self._continental_states = None
        self._tracts = None
        self._gtracts = None
        self._geo_to_tract = None
        self._ghdf = None
        self._overlay = None
        self._zones = None

        self.ea_epsg = 2163  # US Equal Area projection

    @property
    def states(self):
        if self._continental_states is None:
            states = self.pkg.reference('us_states').geoframe()  # US Equal area projection
            self._continental_states = states[~states.stusps.isin(['HI', 'AK', 'PR', 'VI', 'MP', 'GU', 'AS'])]

        return self._continental_states

    def tract_zones(self):
        if self._zones is None:

            tracts = self.tracts

            grd = self.pkg.reference('utm_grid').package.resource('utm_grid').geoframe()
            grd = grd[grd.cus_state == 1]

            frames = []

            for idx, g in grd.groupby('epsg'):
                g['geometry'] = g.to_crs(idx).buffer(15000).to_crs(4326)
                g['epsg'] = idx
                frames.append(g)

            buffered = pd.concat(frames)

            g = gpd.sjoin(grd, tracts)
            b = gpd.sjoin(buffered, tracts)

            self._zones = g, b

        return self._zones

    @property
    def utm_zones(self):
        return self.tract_zones()[0][['geoid','zone', 'epsg']]

    @property
    def utm_buffered_zones(self):
        return self.tract_zones()[1][['geoid','zone', 'epsg']]

    @property
    def tracts(self):

        if self._tracts is None:
            logger.info("Building tracts")

            url_t = self.pkg.reference('us_tracts_template').url
            frames = [rg.geoframe(url_t.format(st=st)) for st in tqdm(stusab.values())]

            tracts = pd.concat(frames).to_crs(4326)

            # Mark the tracts in the continential US
            tracts['continential'] = tracts.statefp.isin(self.states.statefp.unique()).astype(int)
            tracts['tract_id'] = tracts.reset_index().index

            # Need to convert to each UTM zone to get accurate area
            # computation.
            # tracts = tracts.sort_values('geoid').reset_index()
            # frames = [ g.to_crs(int(idx)).area for idx, g in tracts.groupby('utm_epsg')]
            # t = pd.concat(frames).to_frame('utm_area')
            # tracts = tracts.join(t)

            tracts['geohash'] = tracts[['intptlat', 'intptlon']].astype(float).apply(
                lambda r: gh.encode(r.intptlat, r.intptlon), axis=1)

            tracts['gh4'] = tracts.geohash.str.slice(0, 4)

            self._tracts = tracts[
               ['geoid', 'tract_id', 'geohash', 'statefp', 'intptlat', 'intptlon', 'geometry', 'aland', 'awater',
                 'gh4', 'continential']]



        return self._tracts

    @property
    def geohashes(self):

        if self._ghdf is None:
            logger.info("Building geohashes")
            ush = gh.polygon_to_geohash(self.states.unary_union, 4)

            ghdf = gpd.GeoDataFrame({'geohash': ush}, geometry=geohash_to_polygons(ush), crs=4326)
            dims = pd.DataFrame(ghdf.geohash.apply(lambda g: gh.dimensions(g, True)).to_list(), columns=['dx', 'dy'])
            ghdf = pd.concat([ghdf, dims], axis=1)

            # Compute the area in square meters, but we convert each UTM group to the
            # appropriate UTM zone first
            ghdf['utm_epsg'] = ghdf.geohash.apply(lambda v: convert_wgs_to_utm(*gh.decode(v)))
            ghdf['utm_epsg'] = ghdf['utm_epsg'].astype(int)

            frames = [g.to_crs(int(idx)).area for idx, g in ghdf.groupby('utm_epsg')]
            t = pd.concat(frames).to_frame('utm_area')
            ghdf = ghdf.join(t)

            ghdf['gh_area'] = ghdf.dx * ghdf.dy

            self._ghdf = ghdf

        return self._ghdf

        # The differences between the UTM are computation and that from the geohash
        # are also pretty small, also mostly less than 0.2%
        # ( (ghdf.utm_area - ghdf.gh_area) / ghdf.utm_area).describe()

    @property
    def gtracts(self):

        if self._gtracts is None:
            logger.info("Linking gtracts")
            self._gtracts = self.tracts.merge(self.geohashes[['geohash', 'utm_epsg']] \
                                              .rename(columns={'geohash': 'gh4'}), on='gh4', how='left')

        return self._gtracts

    @property
    def geo_to_tract(self):
        """Map from the centroid of the geohashes to tracts"""

        if self._geo_to_tract is None:
            logger.info("Linking gh centroids to tracts")
            t = self.geohashes.copy().to_crs(self.ea_epsg)
            t['geometry'] = t.geometry.centroid
            tracts2163 = self.gtracts.to_crs(self.ea_epsg)
            t = gpd.sjoin(t, tracts2163)

            # Geohashes where the centroid is not in any tract; arround the edges, as you'd expect
            niat = self.geohashes[~self.geohashes.geohash.isin(t.geohash_left)].to_crs(self.ea_epsg)

            # find a link from geohash to tract by ovelap, rather than centroid
            nait = gpd.overlay(niat, tracts2163)
            nait['a'] = nait.area
            nait = nait.sort_values('a', ascending=False).drop_duplicates(subset=['geohash_1'])

            # Combine them together.
            self._geo_to_tract = pd.concat([nait[['geohash_1', 'geoid']].rename(columns={'geohash_1': 'geohash'}),
                                            t[['geohash_left', 'geoid']].rename(columns={'geohash_left': 'geohash'})])

        return self._geo_to_tract

    @property
    def overlay(self):

        if self._overlay is None:

            tracts = self.gtracts
            tracts['tract_id'] = tracts.reset_index().index
            tg = tracts[['tract_id', 'geometry', 'utm_epsg']].groupby('utm_epsg')
            gg = self.geohashes[['geohash', 'utm_epsg', 'geometry']].groupby('utm_epsg')

            frames = []

            for utm_epsg in tqdm(set(list(tg.indices.keys()) + list(gg.indices.keys()))):
                try:
                    t = tg.get_group(utm_epsg).to_crs(int(utm_epsg))
                except KeyError as e:
                    print("ERROR. No tract for ", utm_epsg, e)
                    continue

                try:
                    g = gg.get_group(utm_epsg).to_crs(int(utm_epsg))
                except KeyError as e:
                    print("ERROR. No geohashes for ", utm_epsg, e)
                    continue

                ovl = gpd.overlay(g, t)

                ovl[['ovl_area']] = ovl.area

                frames.append(ovl)

            ovl = pd.concat(frames).drop(columns=['utm_epsg_1', 'utm_epsg_2', 'geometry'])
            print(len(ovl), ovl.geohash.nunique(), ovl.tract_id.nunique(), len(tracts))
            ovl = ovl.merge(tracts[['geoid', 'tract_id', 'aland', 'awater']]).merge(
                self.geohashes[['geohash', 'utm_area']]).rename(columns={'utm_area': 'gh_area'})
            ovl['tract_area'] = ovl.aland + ovl.awater
            ovl['gh_in_tract_prop'] = ovl.ovl_area / ovl.tract_area
            ovl['tract_in_gh_prop'] = ovl.ovl_area / ovl.gh_area

            ovl['ovl_area'] = ovl.ovl_area.astype(int)
            ovl['gh_area'] = ovl.gh_area.astype(int)

            self._overlay = ovl[
                ['geohash', 'tract_id', 'geoid', 'aland', 'awater', 'tract_area', 'gh_area', 'ovl_area', 'gh_in_tract_prop',
                 'tract_in_gh_prop']]

        return self._overlay

    outputs = ('tracts', 'geohashes', 'geo_to_tract','overlay','utm_zones','utm_buffered_zones')

    def build(self, force=False):

        dd = self.pkg_root.joinpath('data')

        if not dd.exists():
            dd.mkdir(parents=True, exist_ok=True)

        for o in self.outputs:
            p = dd.joinpath(o).with_suffix('.csv')
            if not p.exists() or force:
                logger.info(f"Creating {o}{' (forcing)' if force else ''}")
                d = getattr(self,o)
                logger.info(f"Write {o}")
                d.to_csv(p, index=False)
            else:
                logger.info(f"{o} already exists")



