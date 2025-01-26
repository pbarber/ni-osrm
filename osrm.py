# %% Imports and function definitions
import requests
import pandas
import geopandas
import io
import zipfile
from pyproj import Transformer
import os
import json
import re

def download_file_if_not_exists(url, fname=None, jsonkey=None):
    if fname is None:
        fname = os.path.basename(url)
    if not os.path.isfile(fname):
        session = requests.Session()
        if jsonkey is None:
            with session.get(url, stream=True) as stream:
                stream.raise_for_status()
                with open(fname, 'wb') as f:
                    for chunk in stream.iter_content(chunk_size=8192):
                        f.write(chunk)
        else:
            resp = session.get(url)
            resp.raise_for_status()
            print(resp.json())
            with open(fname, 'w') as f:
                json.dump(resp.json().get(jsonkey), f)

def create_points_for_osrm(input, filename):
    buf = input.to_csv(lineterminator=';', header=False, index=False)
    with open(filename, 'w') as fo:
        fo.write(buf[:-1])

def get_matrix_from_osrm(filename, reference, codecol):
    osrm = pandas.read_json(filename)['durations'].explode()
    osrm = osrm.reset_index().rename(columns={'index' : 'from'})
    osrm['to'] = osrm.groupby('from').cumcount()
    osrm = pandas.merge(osrm, reference, how='inner', left_on='to', right_index=True)
    osrm = pandas.merge(osrm, reference, how='inner', left_on='from', right_index=True)
    return osrm.drop(columns=['to','from']).rename(columns={codecol + '_x': 'to', codecol + '_y': 'from'})

# %% Load the population-weighted Data Zone and Super Data Zone centroids and convert to suitable format for OSRM
resp = requests.get('https://www.nisra.gov.uk/system/files/statistics/geography-census-2021-population-weighted-centroids-csv.zip')
resp.raise_for_status()
zf = zipfile.ZipFile(io.BytesIO(resp.content))
trans = Transformer.from_crs("EPSG:29902", "EPSG:4326", always_xy=True)
dfs = {}
for name in zf.namelist():
    coords = pandas.read_csv(zf.open(name))
    coords['centroid_x'],coords['centroid_y'] = trans.transform(coords['X'].values, coords['Y'].values)
    coords.drop(columns=['X','Y'], inplace=True)
    if 'DZ2021_code' in coords.columns:
        dz = coords.set_index('DZ2021_code')[['centroid_x','centroid_y']]
        create_points_for_osrm(dz, 'dz-osrm-formatted-centroids.txt')
    if 'SDZ2021_code' in coords.columns:
        sdz = coords.set_index('SDZ2021_code')[['centroid_x','centroid_y']]
        create_points_for_osrm(sdz, 'sdz-osrm-formatted-centroids.txt')

# %% Load and convert the Small Area centres, note that these are geographic, not population-weighted
coords = geopandas.read_file('sa2011_epsg4326_simplified15.json')
coords = coords[['SA2011','X_COORD','Y_COORD']].sort_values('SA2011').set_index('SA2011')
coords['centre_x'],coords['centre_y'] = trans.transform(coords['X_COORD'].values, coords['Y_COORD'].values)
sa = coords.drop(columns=['X_COORD','Y_COORD'])
create_points_for_osrm(sa, 'sa-osrm-formatted-centroids.txt')

# %% Load back in the matrices
dz_matrix = get_matrix_from_osrm('dz-travel-matrix-2025-01-26.json', dz.reset_index()['DZ2021_code'], 'DZ2021_code')
sdz_matrix = get_matrix_from_osrm('sdz-travel-matrix-2025-01-26.json', sdz.reset_index()['SDZ2021_code'], 'SDZ2021_code')
sa_matrix = get_matrix_from_osrm('sa-travel-matrix-2025-01-26.json', sa.reset_index()['SA2011'], 'SA2011')

# %% Create a single file of the matrices for the smallest geographies: Data Zone and Small Area
pandas.concat([dz_matrix, sa_matrix]).to_csv('ni-osrm-dz-sa-travel-matrix-2025-01-26.csv', index=False)

# %% Load NISRA CPD
download_file_if_not_exists('https://explore.nisra.gov.uk/postcode-search/CPD_LIGHT_JULY_2024.csv')
with open('CPD_LIGHT_JULY_2024.csv', 'r') as fd:
    content = re.sub(r'NEWRY,\s+MOURNE', r'NEWRY\, MOURNE', fd.read())
    content = re.sub(r'Newry,\s+Mourne', r'Newry\, Mourne', content)
    content = re.sub(r'ARMAGH CITY,\s+BANBRIDGE', r'ARMAGH CITY\, BANBRIDGE', content)
    content = re.sub(r'Armagh City,\s+Banbridge', r'Armagh City\, Banbridge', content)
    content = re.sub(r'Armagh,\s+Banbridge', r'Armagh\, Banbridge', content)
    content = re.sub(r'Boho,Cleenish', r'Boho\,Cleenish', content)
    postcodes = pandas.read_csv(io.StringIO(content), escapechar="\\")

# %% As a confirmation, map the shortest travel times to the nearest maternity unit for Small Areas
hospitals = pandas.DataFrame([
    ['Royal Victoria Hospital',      'BT12 6BA', 1],
    ['Belfast City Hospital',        'BT9 7AB',  0],
    ['Ulster Hospital',              'BT16 1RH', 1],
    ['Mater Hospital',               'BT14 6AB', 0],
    ['Antrim Area Hospital',         'BT41 2RL', 1],
    ['Altnagelvin Area Hospital',    'BT47 6SB', 1],
    ['Craigavon Area Hospital',      'BT63 5QQ', 1],
    ['Daisy Hill Hospital',          'BT35 8DR', 1],
    ['South West Acute Hospital',    'BT74 6DN', 1],
    ['Causeway Hospital',            'BT52 1HS', 0],
    ['Mid Ulster Hospital',          'BT45 5EX', 0],
    ['Downe Hospital',               'BT30 6RL', 0],
    ['Lagan Valley Hospital',        'BT28 1JP', 0],
    ['South Tyrone Hospital',        'BT71 4AU', 0],
    ['Robinson Memorial Hospital',   'BT53 6HB', 0]
], columns=['Hospital_Name', 'Postcode', 'Maternity'])
hospitals['Postcode_no_spaces'] = hospitals['Postcode'].str.replace(' ', '')
hospitals = pandas.merge(hospitals, postcodes, how='inner', left_on='Postcode_no_spaces', right_on='postcode')[['Hospital_Name','Postcode','SA2011','DZ2021','Maternity']]

# %% Check for Small Areas
sa_hosps = sa_matrix[sa_matrix['to'].isin(hospitals[hospitals['Maternity']==1]['SA2011'])]
sa_hosps = sa_hosps.sort_values('durations').groupby('from').apply(pandas.DataFrame.head, n=1).reset_index(drop=True)
sa_bounds = geopandas.read_file('sa2011_epsg4326_simplified15.json')
pandas.merge(sa_bounds, sa_hosps, how='inner', left_on='SA2011', right_on='from').plot(column='to')

# %% Check for Data Zones
dz_hosps = dz_matrix[dz_matrix['to'].isin(hospitals[hospitals['Maternity']==1]['DZ2021'])]
dz_hosps = dz_hosps.sort_values('durations').groupby('from').apply(pandas.DataFrame.head, n=1).reset_index(drop=True)
dz_bounds = geopandas.read_file('dz2021_epsg4326_simplified15.geojson')
pandas.merge(dz_bounds, dz_hosps, how='inner', left_on='DZ2021_cd', right_on='from').plot(column='to')

# %%
