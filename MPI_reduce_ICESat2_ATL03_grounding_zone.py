#!/usr/bin/env python
u"""
MPI_reduce_ICESat2_ATL03_grounding_zone.py
Written by Tyler Sutterley (09/2019)

Create masks for reducing ICESat-2 data to within a buffer region near the ice
	sheet grounding zone.  Used to calculate a more definite grounding zone
	from the ICESat-2 data

COMMAND LINE OPTIONS:
	-D X, --directory=X: Working Data Directory
	-B X, --buffer=X: Distance in kilometers to buffer from grounding line
	-M X, --mode=X: Permission mode of directories and files created
	-V, --verbose: Output information about each created file

REQUIRES MPI PROGRAM
	MPI: standardized and portable message-passing system
		https://www.open-mpi.org/
		http://mpitutorial.com/

PYTHON DEPENDENCIES:
	numpy: Scientific Computing Tools For Python
		http://www.numpy.org
		http://www.scipy.org/NumPy_for_Matlab_Users
	mpi4py: MPI for Python
		http://pythonhosted.org/mpi4py/
		http://mpi4py.readthedocs.org/en/stable/
	h5py: Python interface for Hierarchal Data Format 5 (HDF5)
		http://h5py.org
		http://docs.h5py.org/en/stable/mpi.html
	fiona: Python wrapper for vector data access functions from the OGR library
		https://fiona.readthedocs.io/en/latest/manual.html
	shapely: PostGIS-ish operations outside a database context for Python
		http://toblerity.org/shapely/index.html
	pyproj: Python interface to PROJ library
		https://pypi.org/project/pyproj/

PROGRAM DEPENDENCIES:
	convert_julian.py: returns the calendar date and time given a Julian date
	count_leap_seconds.py: determines number of leap seconds for a GPS time

UPDATE HISTORY:
	Updated 09/2019: using fiona for shapefile read and pyproj for coordinates
	Updated 04/2019: check if subsetted beam contains land ice data
	Forked 04/2019 from MPI_reduce_triangulated_grounding_zone.py
	Updated 02/2019: shapely updates for python3 compatibility
	Updated 07/2017: using parts from shapefile
	Written 06/2017
"""
from __future__ import print_function

import sys
import os
import re
import h5py
import fiona
import getopt
import pyproj
import datetime
import numpy as np
from mpi4py import MPI
import shapely.geometry
import shapely.ops
from convert_julian import convert_julian
from count_leap_seconds import count_leap_seconds

#-- buffered shapefile
buffer_shapefile = {}
buffer_shapefile['N'] = 'grn_ice_sheet_buffer_{0:0.0f}km.shp'
buffer_shapefile['S'] = 'ant_ice_sheet_islands_v2_buffer_{0:0.0f}km.shp'
#-- description and reference for each grounded ice file
grounded_description = {}
grounded_description['N'] = 'Greenland Mapping Project (GIMP) Ice & Ocean Mask'
grounded_description['S'] = ('MEaSUREs Antarctic Boundaries for IPY 2007-2009 '
	'from Satellite_Radar, Version 2')
grounded_reference = {}
grounded_reference['N'] = 'http://dx.doi.org/10.5194/tc-8-1509-2014'
grounded_reference['S'] = 'http://dx.doi.org/10.5067/IKBWW4RYHF1Q'

#-- PURPOSE: help module to describe the optional input parameters
def usage():
	print('\nHelp: {}'.format(os.path.basename(sys.argv[0])))
	print(' -D X, --directory=X\tWorking Data Directory')
	print(' -B X, --buffer=X\tDistance in kilometers to buffer grounding line')
	print(' -M X, --mode=X\t\tPermission mode of directories and files created')
	print(' -V, --verbose\t\tOutput information about each created file\n')

#-- PURPOSE: keep track of MPI threads
def info(rank, size):
	print('Rank {0:d} of {1:d}'.format(rank+1,size))
	print('module name: {0}'.format(__name__))
	if hasattr(os, 'getppid'):
		print('parent process: {0:d}'.format(os.getppid()))
	print('process id: {0:d}'.format(os.getpid()))

#-- PURPOSE: set the hemisphere of interest based on the granule
def set_hemisphere(GRANULE):
	if GRANULE in ('10','11','12'):
		projection_flag = 'S'
	elif GRANULE in ('03','04','05'):
		projection_flag = 'N'
	return projection_flag

#-- PURPOSE: load the polygon object for the buffered estimated grounding zone
def load_grounding_zone(base_dir, HEM, BUFFER):
	#-- reading buffered shapefile
	buffered_shapefile = buffer_shapefile[HEM].format(BUFFER)
	shape_input = fiona.open(os.path.join(base_dir,buffered_shapefile))
	epsg = shape_input.crs['init']
	#-- create list of polygons
	polygons = []
	#-- extract the entities and assign by tile name
	for i,ent in enumerate(shape_input.values()):
		#-- list of coordinates
		poly_list = []
		#-- extract coordinates for entity
		for coords in ent['geometry']['coordinates']:
			#-- extract Polar-Stereographic coordinates for record
			x,y = np.transpose(coords)
			poly_list.append(list(zip(x,y)))
		#-- convert poly_list into Polygon object with holes
		poly_obj = shapely.geometry.Polygon(poly_list[0],holes=poly_list[1:])
		#-- Valid Polygon cannot have overlapping exterior or interior rings
		if (not poly_obj.is_valid):
			poly_obj = poly_obj.buffer(0)
		polygons.append(poly_obj)
	#-- create shapely multipolygon object
	mpoly_obj = shapely.geometry.MultiPolygon(polygons)
	#-- close the shapefile
	shape_input.close()
	#-- return the polygon object for the ice sheet
	return (mpoly_obj,buffered_shapefile,epsg)

#-- PURPOSE: read ICESat-2 data from NSIDC or MPI_ICESat2_ATL03.py
#-- reduce data to within buffer of grounding zone
def main():
	#-- start MPI communicator
	comm = MPI.COMM_WORLD

	#-- Read the system arguments listed after the program
	long_options = ['help','directory=','buffer=','verbose','mode=']
	optlist,arglist = getopt.getopt(sys.argv[1:],'hD:B:VM:',long_options)

	#-- working data directory
	base_dir = os.getcwd()
	#-- buffer in kilometers for extracting grounding zone
	BUFFER = 20.0
	#-- verbosity settings
	VERBOSE = False
	#-- permissions mode of the local files (number in octal)
	MODE = 0o775
	for opt, arg in optlist:
		if opt in ('-h','--help'):
			usage() if (comm.rank==0) else None
			sys.exit()
		elif opt in ("-D","--directory"):
			base_dir = os.path.expanduser(arg)
		elif opt in ("-B","-buffer"):
			BUFFER = np.float(arg)
		elif opt in ("-V","--verbose"):
			#-- output module information for process
			info(comm.rank,comm.size)
			VERBOSE = True
		elif opt in ("-M","--mode"):
			MODE = int(arg, 8)

	#-- enter HDF5 file as system argument
	if not arglist:
		raise IOError('No input file entered as system arguments')
	#-- tilde-expansion of listed input file
	FILE = os.path.expanduser(arglist[0])

	#-- read data from input file
	print('{0} -->'.format(FILE)) if (VERBOSE and (comm.rank==0)) else None
	#-- Open the HDF5 file for reading
	fileID = h5py.File(FILE, 'r', driver='mpio', comm=comm)
	DIRECTORY = os.path.dirname(FILE)
	#-- extract parameters from ICESat-2 ATLAS HDF5 file name
	rx = re.compile('(processed_)?(ATL\d{2})_(\d{4})(\d{2})(\d{2})(\d{2})'
		'(\d{2})(\d{2})_(\d{4})(\d{2})(\d{2})_(\d{3})_(\d{2})(.*?).h5$')
	SUB,PRD,YY,MM,DD,HH,MN,SS,TRK,CYCL,GRAN,RL,VERS,AUX = rx.findall(FILE).pop()
	#-- set the hemisphere flag based on ICESat-2 granule
	HEM = set_hemisphere(GRAN)

	#-- read each input beam within the file
	IS2_atl03_beams=[k for k in fileID.keys() if bool(re.match(r'gt\d[lr]',k))]

	#-- number of GPS seconds between the GPS epoch
	#-- and ATLAS Standard Data Product (SDP) epoch
	atlas_sdp_gps_epoch = fileID['ancillary_data']['atlas_sdp_gps_epoch'][:]

	#-- read data on rank 0
	if (comm.rank == 0):
		#-- read shapefile and create shapely multipolygon objects
		mpoly_obj,input_file,epsg = load_grounding_zone(base_dir,HEM,BUFFER)
	else:
		#-- create empty object for list of shapely objects
		mpoly_obj = None
		epsg = None

	#-- Broadcast Shapely multipolygon objects and projection
	mpoly_obj = comm.bcast(mpoly_obj, root=0)
	epsg = comm.bcast(epsg, root=0)
	#-- projections for converting lat/lon to polar stereographic
	proj1 = pyproj.Proj("+init=EPSG:{0:d}".format(4326))
	proj2 = pyproj.Proj("+init={0}".format(epsg))

	#-- copy variables for outputting to HDF5 file
	IS2_atl03_mask = {}
	IS2_atl03_fill = {}
	IS2_atl03_mask_attrs = {}
	#-- number of GPS seconds between the GPS epoch (1980-01-06T00:00:00Z UTC)
	#-- and ATLAS Standard Data Product (SDP) epoch (2018-01-01T00:00:00Z UTC)
	#-- Add this value to delta time parameters to compute full gps_seconds
	IS2_atl03_mask['ancillary_data'] = {}
	IS2_atl03_mask_attrs['ancillary_data'] = {}
	for key in ['atlas_sdp_gps_epoch']:
		#-- get each HDF5 variable
		IS2_atl03_mask['ancillary_data'][key] = fileID['ancillary_data'][key][:]
		#-- Getting attributes of group and included variables
		IS2_atl03_mask_attrs['ancillary_data'][key] = {}
		for att_name,att_val in fileID['ancillary_data'][key].attrs.items():
			IS2_atl03_mask_attrs['ancillary_data'][key][att_name] = att_val

	#-- for each input beam within the file
	for gtx in sorted(IS2_atl03_beams):
		#-- output data dictionaries for beam
		IS2_atl03_mask[gtx] = dict(heights={},subsetting={})
		IS2_atl03_fill[gtx] = dict(heights={},subsetting={})
		IS2_atl03_mask_attrs[gtx] = dict(heights={},subsetting={})

		#-- number of photon events
		n_pe, = fileID[gtx]['heights']['h_ph'].shape
		#-- define indices to run for specific process
		ind = np.arange(comm.Get_rank(), n_pe, comm.Get_size(), dtype=np.int)

		#-- extract delta time
		delta_time = fileID[gtx]['heights']['delta_time'][:]
		#-- extract lat/lon
		longitude = fileID[gtx]['heights']['lon_ph'][:]
		latitude = fileID[gtx]['heights']['lat_ph'][:]
		#-- convert lat/lon to polar stereographic
		X,Y = pyproj.transform(proj1, proj2, longitude, latitude)

		#-- convert reduced x and y to shapely multipoint object
		xy_point = MultiPoint(list(zip(X[ind], Y[ind])))

		#-- create distributed intersection map for calculation
		distributed_map = np.zeros((n_pe),dtype=np.bool)
		#-- create empty intersection map array for receiving
		associated_map = np.zeros((n_pe),dtype=np.bool)
		#-- for each polygon
		for poly_obj in mpoly_obj:
			#-- finds if points are encapsulated (in grounding zone)
			int_test = poly_obj.intersects(xy_point)
			if int_test:
				#-- extract intersected points
				int_map = list(map(poly_obj.intersects,xy_point))
				int_indices, = np.nonzero(int_map)
				#-- set distributed_map indices to True for intersected points
				distributed_map[ind[int_indices]] = True
		#-- communicate output MPI matrices between ranks
		#-- operation is a logical "or" across the elements.
		comm.Allreduce(sendbuf=[distributed_map, MPI.BOOL], \
			recvbuf=[associated_map, MPI.BOOL], op=MPI.LOR)
		distributed_map = None
		#-- wait for all processes to finish calculation
		comm.Barrier()

		#-- group attributes for beam
		IS2_atl03_mask_attrs[gtx]['Description'] = fileID[gtx].attrs['Description']
		IS2_atl03_mask_attrs[gtx]['atlas_pce'] = fileID[gtx].attrs['atlas_pce']
		IS2_atl03_mask_attrs[gtx]['atlas_beam_type'] = fileID[gtx].attrs['atlas_beam_type']
		IS2_atl03_mask_attrs[gtx]['groundtrack_id'] = fileID[gtx].attrs['groundtrack_id']
		IS2_atl03_mask_attrs[gtx]['atmosphere_profile'] = fileID[gtx].attrs['atmosphere_profile']
		IS2_atl03_mask_attrs[gtx]['atlas_spot_number'] = fileID[gtx].attrs['atlas_spot_number']
		IS2_atl03_mask_attrs[gtx]['sc_orientation'] = fileID[gtx].attrs['sc_orientation']
		#-- group attributes for heights
		IS2_atl03_mask_attrs[gtx]['heights']['Description'] = ("Contains arrays of the "
			"parameters for each received photon.")
		IS2_atl03_mask_attrs[gtx]['heights']['data_rate'] = ("Data are stored at the "
			"photon detection rate.")

		#-- geolocation, time and segment ID
		#-- delta time
		IS2_atl03_mask[gtx]['heights']['delta_time'] = delta_time
		IS2_atl03_fill[gtx]['heights']['delta_time'] = None
		IS2_atl03_mask_attrs[gtx]['heights']['delta_time'] = {}
		IS2_atl03_mask_attrs[gtx]['heights']['delta_time']['units'] = "seconds since 2018-01-01"
		IS2_atl03_mask_attrs[gtx]['heights']['delta_time']['long_name'] = "Elapsed GPS seconds"
		IS2_atl03_mask_attrs[gtx]['heights']['delta_time']['standard_name'] = "time"
		IS2_atl03_mask_attrs[gtx]['heights']['delta_time']['calendar'] = "standard"
		IS2_atl03_mask_attrs[gtx]['heights']['delta_time']['description'] = ("Number of GPS "
			"seconds since the ATLAS SDP epoch. The ATLAS Standard Data Products (SDP) epoch offset "
			"is defined within /ancillary_data/atlas_sdp_gps_epoch as the number of GPS seconds "
			"between the GPS epoch (1980-01-06T00:00:00.000000Z UTC) and the ATLAS SDP epoch. By "
			"adding the offset contained within atlas_sdp_gps_epoch to delta time parameters, the "
			"time in gps_seconds relative to the GPS epoch can be computed.")
		IS2_atl03_mask_attrs[gtx]['heights']['delta_time']['coordinates'] = \
			"lat_ph lon_ph"
		#-- latitude
		IS2_atl03_mask[gtx]['heights']['latitude'] = latitude
		IS2_atl03_fill[gtx]['heights']['latitude'] = None
		IS2_atl03_mask_attrs[gtx]['heights']['latitude'] = {}
		IS2_atl03_mask_attrs[gtx]['heights']['latitude']['units'] = "degrees_north"
		IS2_atl03_mask_attrs[gtx]['heights']['latitude']['contentType'] = "physicalMeasurement"
		IS2_atl03_mask_attrs[gtx]['heights']['latitude']['long_name'] = "Latitude"
		IS2_atl03_mask_attrs[gtx]['heights']['latitude']['standard_name'] = "latitude"
		IS2_atl03_mask_attrs[gtx]['heights']['latitude']['description'] = ("Latitude of each "
			"received photon. Computed from the ECF Cartesian coordinates of the bounce point.")
		IS2_atl03_mask_attrs[gtx]['heights']['latitude']['valid_min'] = -90.0
		IS2_atl03_mask_attrs[gtx]['heights']['latitude']['valid_max'] = 90.0
		IS2_atl03_mask_attrs[gtx]['heights']['latitude']['coordinates'] = \
			"delta_time lon_ph"
		#-- longitude
		IS2_atl03_mask[gtx]['heights']['longitude'] = longitude
		IS2_atl03_fill[gtx]['heights']['longitude'] = None
		IS2_atl03_mask_attrs[gtx]['heights']['longitude'] = {}
		IS2_atl03_mask_attrs[gtx]['heights']['longitude']['units'] = "degrees_east"
		IS2_atl03_mask_attrs[gtx]['heights']['longitude']['contentType'] = "physicalMeasurement"
		IS2_atl03_mask_attrs[gtx]['heights']['longitude']['long_name'] = "Longitude"
		IS2_atl03_mask_attrs[gtx]['heights']['longitude']['standard_name'] = "longitude"
		IS2_atl03_mask_attrs[gtx]['heights']['longitude']['description'] = ("Longitude of each "
			"received photon. Computed from the ECF Cartesian coordinates of the bounce point.")
		IS2_atl03_mask_attrs[gtx]['heights']['longitude']['valid_min'] = -180.0
		IS2_atl03_mask_attrs[gtx]['heights']['longitude']['valid_max'] = 180.0
		IS2_atl03_mask_attrs[gtx]['heights']['longitude']['coordinates'] = \
			"delta_time lat_ph"

		#-- subsetting variables
		IS2_atl03_mask_attrs[gtx]['subsetting']['Description'] = ("The subsetting group "
			"contains parameters used to reduce photon events to specific regions of interest.")
		IS2_atl03_mask_attrs[gtx]['subsetting']['data_rate'] = ("Data are stored at the photon "
			"detection rate.")

		#-- output mask to HDF5
		IS2_atl03_mask[gtx]['subsetting']['ice_gz'] = associated_map
		IS2_atl03_mask_attrs[gtx]['subsetting']['ice_gz'] = {}
		IS2_atl03_mask_attrs[gtx]['subsetting']['ice_gz']['contentType'] = "referenceInformation"
		IS2_atl03_mask_attrs[gtx]['subsetting']['ice_gz']['long_name'] = 'Grounding Zone Mask'
		IS2_atl03_mask_attrs[gtx]['subsetting']['ice_gz']['description'] = ("Grounding zone mask "
			"calculated using delineations from {0} buffered by {1:0.0f} km.".format(grounded_description[HEM],BUFFER))
		IS2_atl03_mask_attrs[gtx]['subsetting']['ice_gz']['reference'] = grounded_reference[HEM]
		IS2_atl03_mask_attrs[gtx]['subsetting']['ice_gz']['source'] = BUFFER
		IS2_atl03_mask_attrs[gtx]['subsetting']['ice_gz']['coordinates'] = \
			"../heights/delta_time ../heights/lat_ph ../heights/lon_ph"
		#-- wait for all processes to finish calculation
		comm.Barrier()

	#-- parallel h5py I/O does not support compression filters at this time
	if (comm.rank == 0) and associated_map.any():
		#-- output HDF5 files with output masks
		args = (PRD,'GROUNDING_ZONE_MASK',YY,MM,DD,HH,MN,SS,TRK,CYCL,GRAN,RL,VERS,AUX)
		file_format='{0}_{1}_{2}{3}{4}{5}{6}{7}_{8}{9}{10}_{11}_{12}{13}.h5'
		#-- print file information
		print('\t{0}'.format(file_format.format(*args))) if VERBOSE else None
		HDF5_ATL06_mask_write(IS2_atl03_mask, IS2_atl03_mask_attrs, CLOBBER='Y',
			INPUT=os.path.basename(FILE), FILL_VALUE=IS2_atl03_fill,
			FILENAME=os.path.join(DIRECTORY,file_format.format(*args)))
		#-- change the permissions mode
		os.chmod(os.path.join(DIRECTORY,file_format.format(*args)), MODE)
	#-- close the input file
	fileID.close()

#-- PURPOSE: outputting the interpolated DEM data for ICESat-2 data to HDF5
def HDF5_ATL03_mask_write(IS2_atl03_mask, IS2_atl03_attrs, INPUT=None,
	FILENAME='', FILL_VALUE=None, CLOBBER='Y'):
	#-- setting HDF5 clobber attribute
	if CLOBBER in ('Y','y'):
		clobber = 'w'
	else:
		clobber = 'w-'

	#-- open output HDF5 file
	fileID = h5py.File(os.path.expanduser(FILENAME), clobber)

	#-- create HDF5 records
	h5 = {}

	#-- number of GPS seconds between the GPS epoch (1980-01-06T00:00:00Z UTC)
	#-- and ATLAS Standard Data Product (SDP) epoch (2018-01-01T00:00:00Z UTC)
	h5['ancillary_data'] = {}
	for k,v in IS2_atl03_mask['ancillary_data'].items():
		#-- Defining the HDF5 dataset variables
		val = 'ancillary_data/{0}'.format(k)
		h5['ancillary_data'][k] = fileID.create_dataset(val, np.shape(v), data=v,
			dtype=v.dtype, compression='gzip')
		#-- add HDF5 variable attributes
		for att_name,att_val in IS2_atl03_attrs['ancillary_data'][k].items():
			h5['ancillary_data'][k].attrs[att_name] = att_val

	#-- write each output beam
	beams = [k for k in IS2_atl03_mask.keys() if bool(re.match(r'gt\d[lr]',k))]
	for gtx in beams:
		fileID.create_group(gtx)
		#-- add HDF5 group attributes for beam
		for att_name in ['Description','atlas_pce','atlas_beam_type',
			'groundtrack_id','atmosphere_profile','atlas_spot_number',
			'sc_orientation']:
			fileID[gtx].attrs[att_name] = IS2_atl03_attrs[gtx][att_name]
		#-- create heights group
		fileID[gtx].create_group('heights')
		h5[gtx] = dict(heights={})
		for att_name in ['Description','data_rate']:
			att_val = IS2_atl03_attrs[gtx]['heights'][att_name]
			fileID[gtx]['heights'].attrs[att_name] = att_val

		#-- delta_time
		v = IS2_atl03_mask[gtx]['heights']['delta_time']
		attrs = IS2_atl03_attrs[gtx]['heights']['delta_time']
		#-- Defining the HDF5 dataset variables
		val = '{0}/{1}/{2}'.format(gtx,'heights','segment_id')
		h5[gtx]['heights']['delta_time'] = fileID.create_dataset(val,
			np.shape(v), data=v, dtype=v.dtype, compression='gzip')
		#-- add HDF5 variable attributes
		for att_name,att_val in attrs.items():
			h5[gtx]['heights']['delta_time'].attrs[att_name] = att_val

		#-- geolocation variables
		for k in ['latitude','longitude']:
			#-- values and attributes
			v = IS2_atl03_mask[gtx]['heights'][k]
			attrs = IS2_atl03_attrs[gtx]['heights'][k]
			fillvalue = FILL_VALUE[gtx]['heights'][k]
			#-- Defining the HDF5 dataset variables
			val = '{0}/{1}/{2}'.format(gtx,'heights',k)
			if fillvalue:
				h5[gtx]['heights'][k] = fileID.create_dataset(val, np.shape(v),
					data=v,dtype=v.dtype,fillvalue=fillvalue,compression='gzip')
			else:
				h5[gtx]['heights'][k] = fileID.create_dataset(val, np.shape(v),
					data=v, dtype=v.dtype, compression='gzip')
			#-- attach dimensions
			for dim in ['delta_time']:
				h5[gtx]['heights'][k].dims.create_scale(
					h5[gtx]['heights'][dim], dim)
				h5[gtx]['heights'][k].dims[0].attach_scale(
					h5[gtx]['heights'][dim])
			#-- add HDF5 variable attributes
			for att_name,att_val in attrs.items():
				h5[gtx]['heights'][k].attrs[att_name] = att_val

		#-- create subsetting group
		fileID[gtx].create_group('subsetting')
		h5[gtx]['subsetting'] = {}
		for att_name in ['Description','data_rate']:
			att_val = IS2_atl03_attrs[gtx]['subsetting'][att_name]
			fileID[gtx]['subsetting'].attrs[att_name] = att_val
		#-- add to subsetting variables
		for k,v in IS2_atl03_mask[gtx]['subsetting'].items():
			#-- attributes
			attrs = IS2_atl03_attrs[gtx]['subsetting'][k]
			#-- Defining the HDF5 dataset variables
			val = '{0}/{1}/{2}'.format(gtx,'subsetting',k)
			h5[gtx]['subsetting'][k] = fileID.create_dataset(val, np.shape(v),
				data=v, dtype=v.dtype, compression='gzip')
			#-- attach dimensions
			for dim in ['delta_time']:
				h5[gtx]['subsetting'][k].dims.create_scale(
					h5[gtx]['heights'][dim], dim)
				h5[gtx]['subsetting'][k].dims[0].attach_scale(
					h5[gtx]['heights'][dim])
			#-- add HDF5 variable attributes
			for att_name,att_val in attrs.items():
				h5[gtx]['subsetting'][k].attrs[att_name] = att_val

	#-- HDF5 file title
	fileID.attrs['featureType'] = 'trajectory'
	fileID.attrs['title'] = 'ATLAS/ICESat-2 L2A Global Geolocated Photon Data'
	fileID.attrs['summary'] = ("The purpose of ATL03 is to provide along-track "
		"photon data for all 6 ATLAS beams and associated statistics.")
	fileID.attrs['description'] = ("Photon heights determined by ATBD "
		"Algorithm using POD and PPD. All photon events per transmit pulse per "
		"beam. Includes POD and PPD vectors. Classification of each photon by "
		"several ATBD Algorithms.")
	date_created = datetime.datetime.today()
	fileID.attrs['date_created'] = date_created.isoformat()
	project = 'ICESat-2 > Ice, Cloud, and land Elevation Satellite-2'
	fileID.attrs['project'] = project
	platform = 'ICESat-2 > Ice, Cloud, and land Elevation Satellite-2'
	fileID.attrs['project'] = platform
	#-- add attribute for elevation instrument and designated processing level
	instrument = 'ATLAS > Advanced Topographic Laser Altimeter System'
	fileID.attrs['instrument'] = instrument
	fileID.attrs['source'] = 'Spacecraft'
	fileID.attrs['references'] = 'http://nsidc.org/data/icesat2/data.html'
	fileID.attrs['processing_level'] = '4'
	#-- add attributes for input ATL03 and ATL09 files
	fileID.attrs['input_files'] = ','.join([os.path.basename(i) for i in INPUT])
	#-- find geospatial and temporal ranges
	lnmn,lnmx,ltmn,ltmx,tmn,tmx = (np.inf,-np.inf,np.inf,-np.inf,np.inf,-np.inf)
	for gtx in beams:
		lon = IS2_atl03_mask[gtx]['heights']['longitude']
		lat = IS2_atl03_mask[gtx]['heights']['latitude']
		delta_time = IS2_atl03_mask[gtx]['heights']['delta_time']
		#-- setting the geospatial and temporal ranges
		lnmn = lon.min() if (lon.min() < lnmn) else lnmn
		lnmx = lon.max() if (lon.max() > lnmx) else lnmx
		ltmn = lat.min() if (lat.min() < ltmn) else ltmn
		ltmx = lat.max() if (lat.max() > ltmx) else ltmx
		tmn = delta_time.min() if (delta_time.min() < tmn) else tmn
		tmx = delta_time.max() if (delta_time.max() > tmx) else tmx
	#-- add geospatial and temporal attributes
	fileID.attrs['geospatial_lat_min'] = ltmn
	fileID.attrs['geospatial_lat_max'] = ltmx
	fileID.attrs['geospatial_lon_min'] = lnmn
	fileID.attrs['geospatial_lon_max'] = lnmx
	fileID.attrs['geospatial_lat_units'] = "degrees_north"
	fileID.attrs['geospatial_lon_units'] = "degrees_east"
	fileID.attrs['geospatial_ellipsoid'] = "WGS84"
	fileID.attrs['date_type'] = 'UTC'
	fileID.attrs['time_type'] = 'CCSDS UTC-A'
	#-- convert start and end time from ATLAS SDP seconds into Julian days
	atlas_sdp_gps_epoch=IS2_atl03_mask['ancillary_data']['atlas_sdp_gps_epoch']
	gps_seconds = atlas_sdp_gps_epoch + np.array([tmn,tmx])
	time_leaps = count_leap_seconds(gps_seconds)
	time_julian = 2444244.5 + (gps_seconds - time_leaps)/86400.0
	#-- convert to calendar date with convert_julian.py
	YY,MM,DD,HH,MN,SS = convert_julian(time_julian,FORMAT='tuple')
	#-- add attributes with measurement date start, end and duration
	tcs = datetime.datetime(np.int(YY[0]), np.int(MM[0]), np.int(DD[0]),
		np.int(HH[0]), np.int(MN[0]), np.int(SS[0]), np.int(1e6*(SS[0] % 1)))
	fileID.attrs['time_coverage_start'] = tcs.isoformat()
	tce = datetime.datetime(np.int(YY[1]), np.int(MM[1]), np.int(DD[1]),
		np.int(HH[1]), np.int(MN[1]), np.int(SS[1]), np.int(1e6*(SS[1] % 1)))
	fileID.attrs['time_coverage_end'] = tce.isoformat()
	fileID.attrs['time_coverage_duration'] = '{0:0.0f}'.format(tmx-tmn)
	#-- Closing the HDF5 file
	fileID.close()

#-- run main program
if __name__ == '__main__':
	main()
