# OSRM for NI

Building a travel times dataset for NI using [OSRM](https://project-osrm.org/). Uses Docker, setup is based on [this gist](https://gist.github.com/AlexandraKapp/e0eee2beacc93e765113aff43ec77789).

## Set up the ORSM server

Visit the [Geofabrik downloads page](https://download.geofabrik.de/) and navigate through the Europe section to download the latest [Ireland and Northern Ireland](https://download.geofabrik.de/europe/ireland-and-northern-ireland.html) OSM PBF.

Once you have the file downloaded, place it in the directory holding this readme and then run the following commands. These commands will set up the server in Docker, using the downloaded file as the reference data.

```sh
docker pull osrm/osrm-backend
docker run -t -v .:/data osrm/osrm-backend osrm-extract -p /opt/car.lua /data/ireland-and-northern-ireland-latest.osm.pbf
docker run -t -v .:/data osrm/osrm-backend osrm-partition /data/ireland-and-northern-ireland-latest.osm
docker run -t -v .:/data osrm/osrm-backend osrm-customize /data/ireland-and-northern-ireland-latest.osm
```

## Start the OSRM server

Once the server is set up it will create lots of files in this directory.

Run the following command to start the server, 

```sh
docker run -t -i -p 5500:5000 -v .:/data osrm/osrm-backend osrm-routed --algorithm mld --max-table-size 5000 /data/ireland-and-northern-ireland-latest.osrm
```

The server command will now wait for HTTP requests on port 5500.

## Prepare your request

In order to make a request for a travel time matrix between a list of points, you will need to format the coordinates of those points as follows:

- longitude (x) and latitude (y) in WGS84 projection, separated by comma
- coordinates separated by semicolon, with no semicolon for the last entry in the list

An example of 3 points represented in the required format is:

```
-6.218373577558905,54.6550358077733;-6.212844457965391,54.62955519134457;-7.462426271815877,54.81260831700859
```

Handling long strings of coordinates is best done via a file. A Python example of producing such a file from a geopandas dataframe is:

```python
import pandas

def create_points_for_osrm(input, filename):
    buf = input.to_csv(lineterminator=';', header=False, index=False)
    with open(filename, 'w') as fo:
        fo.write(buf[:-1])

points = dataset.sort_values('MYKEY').set_index('MYKEY')[['x','y']]
create_points_for_osrm(mykey, 'formatted-coordinates.txt')
```

It is important to sort the output by a unique key for the points as the process of creating the travel times matrix will not preserve any identifiers, so these will need to be recreated afterwards based on the ordering of the results. To do this replace `MYKEY` with the name of the key for your points.

## Make a request

Once you have the file of formatted, ordered coordinates and the server running, you can build the travel matrix using the following command:

```sh
curl "http://localhost:5500/table/v1/driving/$(cat formatted-coordinates.txt)" > travel-matrix-YYYYMMDD.json
```

I find it useful to manually add a datestamp at the end of the filename.

## Process the result

Once the `curl` command above has completed, it should produce a JSON file containing the travel times. To load this into a Python pandas dataframe and convert it to a CSV file, use:

```python
import pandas

def get_matrix_from_osrm(filename, reference, codecol):
    osrm = pandas.read_json(filename)['durations'].explode()
    osrm = osrm.reset_index().rename(columns={'index' : 'from'})
    osrm['to'] = osrm.groupby('from').cumcount()
    osrm = pandas.merge(osrm, reference, how='inner', left_on='to', right_index=True)
    osrm = pandas.merge(osrm, reference, how='inner', left_on='from', right_index=True)
    return osrm.drop(columns=['to','from']).rename(columns={codecol + '_x': 'to', codecol + '_y': 'from'})

matrix = get_matrix_from_orsm('travel-matrix-YYYYMMDD.json', points.reset_index()['MYKEY'], 'MYKEY')
matrix.to_csv('travel-matrix-YYYYMMDD.csv', index=False)
```

Note that the above reuses the `points` data from when the request data file was created, replace `MYKEY` with the name of the unique key for your points.
