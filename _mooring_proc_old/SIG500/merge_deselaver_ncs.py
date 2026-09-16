# ### SIG500 processing

# #### Concatenating velocity files from OceanContour - Burst_*VTC.DSEL.AVER.nc

import numpy as np
import xarray as xr
import pandas as pd
import os
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
import glob
import datetime

# Hard coded parameters

pres_min = 20.0

# to Convert time using TimeStamp seconds since 1970 -> days since 1950 (gregorian)
secperday = 86400.0
epoch_1950 = pd.Timestamp('1950-01-01 00:00:00', tz='UTC')
seconds_offset_1950_to_1970 = (pd.Timestamp('1970-01-01 00:00:00', tz='UTC') - epoch_1950).total_seconds()
days_offset_1950_to_1970 = seconds_offset_1950_to_1970 / secperday 
matlab_offset_1950 = 712224  # datenum of 1950-01-01
time_units = 'days since 1950-01-01 00:00:00'
time_calendar = 'gregorian'
time_type = 'float64'

# files and folders

fgenv = "BASJAS_V_202603"
fgenz = "BASJAS_Z_202603"
inrec_folder = "/datasets/work/oa-srsalt/work/preqa/SWOT/cal_val/jason_calval/all_mooring_data/proc_1/rec_202603"
input_folder = inrec_folder+"/BASJAS_PTSUVW_202603/SIG500_103017/Exported_Data/S103017A002_BSJSN2502_0000/Burst"
os.chdir(input_folder)

outrec_folder = "/datasets/work/oa-srsalt/work/preqa/SWOT/cal_val/jason_calval/all_mooring_data/proc_2/rec_202603"
output_folder = outrec_folder+"/BASJAS_PTSUVW_202603/SIG500_103017"
output_file_temp = os.path.join(output_folder, fgenv+"_temp.nc")

output_file_z = os.path.join(output_folder, fgenz+"_swapdims.nc")

# to read data
in_group = 'Data/Burst'


# Create output folder for plots
plot_folder = output_folder
os.makedirs(plot_folder, exist_ok=True)

# list of files to concatenate
filist = sorted(glob.glob("Burst_???.VTC.DSEL.AVER.nc"))
list_ind = range(len(filist)-1)
list_ind

for ific in list_ind :
    file_in = filist[ific+1]
    print(file_in)


# Open first file with decode_times=False to avoid timestamp overflow
file_in=filist[0]
ds = xr.open_dataset(file_in, group=in_group, decode_times=False)

# drop the start of the record where the instrument is not deployed with a test on Pressure
# ds = ds.where(ds.Altimeter_Pressure > pres_min, drop=True)

# Convert time using TimeStamp seconds since 1970 -> days since 1950 (gregorian)

if 'TimeStamp' in ds.variables:
    ts_sec = ds['TimeStamp'].values.astype('float64')
    time_days = ts_sec / secperday + days_offset_1950_to_1970
    ds = ds.assign_coords(time=time_days.astype('float64'))
    ds['time'].encoding.update({
        'units': time_units,
        'calendar': time_calendar,
        'dtype': time_type 
    })

# Concatenate all remaining files
list_ind = range(len(filist)-1)
for ific in list_ind:
    file_in = filist[ific+1]
    print('reading ',file_in, ific, '/',list_ind[:-1])
    ds2 = xr.open_dataset(file_in, group=in_group, decode_times=False)
    
    # Manually convert TimeStamp seconds to days since 1950
    if 'TimeStamp' in ds2.variables:
        ts_sec2 = ds2['TimeStamp'].values.astype('float64')
        time_days2 = ts_sec2 / secperday+ days_offset_1950_to_1970
        ds2 = ds2.assign_coords(time=time_days2.astype('float64'))
        ds2['time'].encoding.update({
            'units': time_units,
            'calendar': time_calendar,
            'dtype': time_type
        })
    
    # Use concat for time series data
    print('... concatenate')
    ds = xr.concat([ds, ds2], dim='time')

# Drop the start and end of the record where the instrument is not deployed with a test on Pressure
ds = ds.where(ds.Altimeter_Pressure > pres_min, drop=True)
ds

# Save with time encoded as days since 1950-01-01 00:00:00 UTC

ds.to_netcdf(output_file_temp)

# output_folder = "/datasets/work/oa-srsalt/work/preqa/SWOT/cal_val/jason_calval/all_mooring_data/proc_2/rec_202508/BASS3B_PTSUVW_202508/SIG500_104424"
# os.chdir(output_folder)


# Process BASS3B_Z_202508.nc
file_in = output_file_temp
ds_z = xr.open_dataset(file_in, decode_times=False)

# Create TIME as the primary dimension from TimeStamp
if 'TimeStamp' in ds_z.variables:
    ts_sec_z = ds_z['TimeStamp'].values.astype('float64')
    time_days_z = ts_sec_z / secperday + days_offset_1950_to_1970
    
    # Keep original 'time' as 'time_instrument' variable before renaming
    time_days_instrument = ds_z['time'].values.astype('float64')
    ds_z['time_instrument'] = (('time',), time_days_instrument)
    ds_z['time_instrument'].attrs.update({
        'units': time_units,
        'calendar': time_calendar,
        'description': 'Instrument time dimension'
    })
    ds_z['time_instrument'].encoding = {'_FillValue': None}
    
    # Rename 'time' dimension to 'TIME' and reassign with TimeStamp values
    ds_z = ds_z.rename({'time': 'TIME'})
    ds_z = ds_z.assign_coords(TIME=time_days_z.astype('float64'))
    ds_z['TIME'].attrs.update({
        'units': time_units,
        'long_name': 'time',
        'short_name': 'time',
        'axis': 'T',
        'valid_min': '0.0',
        'valid_max': '90000.0',
        'calendar': time_calendar 
    })
    ds_z['TIME'].encoding = {'_FillValue': None}
    
    # Drop TimeStamp as we no longer need it
    ds_z = ds_z.drop_vars('TimeStamp')

# Add MatlabTimeStamp as data variable: convert TIME to MATLAB datenum
matlab_offset_1950 = 712224  # datenum of 1950-01-01
if 'TIME' in ds_z.coords:
    matlab_datenum = ds_z['TIME'].values + matlab_offset_1950
    ds_z['MatlabTimeStamp'] = (('TIME',), matlab_datenum.astype('float64'))
    ds_z['MatlabTimeStamp'].attrs.update({
        'description': 'Instrument timestamp as MATLAB datenum (days)',
        'units': 'days since 1950-01-01 00:00:00'
    })
    ds_z['MatlabTimeStamp'].encoding = {'_FillValue': None}

# Add long_name and standard_name to all variables that don't have them
for var in ds_z.data_vars:
    if 'long_name' not in ds_z[var].attrs:
        ds_z[var].attrs['long_name'] = var
    if 'standard_name' not in ds_z[var].attrs:
        ds_z[var].attrs['standard_name'] = var

# Add long_name and standard_name to all coordinates that don't have them
for coord in ds_z.coords:
    if 'long_name' not in ds_z[coord].attrs:
        ds_z[coord].attrs['long_name'] = coord
    if 'standard_name' not in ds_z[coord].attrs:
        ds_z[coord].attrs['standard_name'] = coord

# Fix units attribute - replace "---" with empty string
for var in ds_z.data_vars:
    if 'units' in ds_z[var].attrs and ds_z[var].attrs['units'] == '---':
        ds_z[var].attrs['units'] = ''

for coord in ds_z.coords:
    if 'units' in ds_z[coord].attrs and ds_z[coord].attrs['units'] == '---':
        ds_z[coord].attrs['units'] = ''

# Save the processed file without CF time encoding to avoid overflow
# output_file_z = os.path.join(output_folder, "BASS3B_V_202508_swapdims.nc")
ds_z.to_netcdf(output_file_z)
# Clean up temporary file
os.remove(output_file_temp)
print(f"Saved: {output_file_z}")

# ============================================================
## PLOTS ##
# ============================================================

# Open dataset for plotting - use chunks if dask is available
try:
    ds = xr.open_dataset(output_file_z, chunks={'TIME': 1000}, decode_times=False)
except ValueError:
    # Dask not available, open without chunking
    ds = xr.open_dataset(output_file_z, decode_times=False)

# start_plot = datetime.datetime(2023, 2, 14, 00)
# start_plot = datetime.datetime(2024, 7, 31, 00)
start_plot = datetime.datetime(2025, 2, 11, 00)
# end_plot = datetime.datetime(2023, 8, 6, 00)
# end_plot = datetime.datetime(2025, 8, 23, 00)
end_plot = datetime.datetime(2026, 3, 11, 00)

# Convert datetime to days since 1950 for slicing
epoch_1950_naive = pd.Timestamp('1950-01-01 00:00:00')
start_days = (pd.Timestamp(start_plot) - epoch_1950_naive).total_seconds() /secperday
end_days = (pd.Timestamp(end_plot) - epoch_1950_naive).total_seconds() / secperday
dsc=ds.sel(TIME=slice(start_days, end_days))

# Convert TIME to datetime for plotting
time_datetime = pd.to_datetime(dsc.TIME.values, unit='D', origin=pd.Timestamp('1950-01-01'))

# Downsample for faster plotting
downsample = 10  # Adjust this value - higher = faster but less detail

# Create output folder for plots
plot_folder = output_folder
os.makedirs(plot_folder, exist_ok=True)

# Plot Altimeter data
plt.figure(figsize=(15,5))
plt.plot(time_datetime[::downsample], dsc.Altimeter_AST[::downsample])
plt.xlabel('Time')
plt.ylabel('Altimeter AST (m)')
plt.title('Altimeter AST (Selected Period - Downsampled)')
plt.grid(True)
plt.gcf().autofmt_xdate()  # Rotate date labels
plot_file = os.path.join(plot_folder, fgenv+'_Altimeter.png')
plt.savefig(plot_file, dpi=150, bbox_inches='tight')
print(f"Saved plot: {plot_file}")
plt.close()

# Plot velocity data - East and North components
if 'Vel_East' in dsc.variables and 'Vel_North' in dsc.variables:
    plt.figure(figsize=(15,5))
    # Plot mean across all range bins
    vel_east_mean = dsc.Vel_East.mean(dim='BurstVelocityENU_Range')
    vel_north_mean = dsc.Vel_North.mean(dim='BurstVelocityENU_Range')
    plt.plot(time_datetime[::downsample], vel_east_mean[::downsample], label='East', linewidth=1)
    plt.plot(time_datetime[::downsample], vel_north_mean[::downsample], label='North', linewidth=1)
    plt.xlabel('Time')
    plt.ylabel('Mean Velocity (m/s)')
    plt.title('Burst Velocity - East & North (Mean across depth bins)')
    plt.legend()
    plt.grid(True)
    plt.gcf().autofmt_xdate()  # Rotate date labels
    plot_file = os.path.join(plot_folder, fgenv+'_Velocity_EastNorth.png')
    plt.savefig(plot_file, dpi=150, bbox_inches='tight')
    print(f"Saved plot: {plot_file}")
    plt.close()
else:
    print("Warning: Vel_East or Vel_North not found in dataset")

# Plot vertical velocity components if available
if 'Vel_Up1' in dsc.variables:
    plt.figure(figsize=(15,5))
    vel_up1_mean = dsc.Vel_Up1.mean(dim='BurstVelocityENU_Range')
    plt.plot(time_datetime[::downsample], vel_up1_mean[::downsample], label='Up1', linewidth=1)
    if 'Vel_Up2' in dsc.variables:
        vel_up2_mean = dsc.Vel_Up2.mean(dim='BurstVelocityENU_Range')
        plt.plot(time_datetime[::downsample], vel_up2_mean[::downsample], label='Up2', linewidth=1)
    plt.xlabel('Time')
    plt.ylabel('Mean Vertical Velocity (m/s)')
    plt.title('Burst Velocity - Vertical Components (Mean across depth bins)')
    plt.legend()
    plt.grid(True)
    plt.gcf().autofmt_xdate()  # Rotate date labels
    plot_file = os.path.join(plot_folder, fgenv+'_Velocity_Vertical.png')
    plt.savefig(plot_file, dpi=150, bbox_inches='tight')
    print(f"Saved plot: {plot_file}")
    plt.close()




