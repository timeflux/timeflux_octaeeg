import pandas as pd

# fname = "20240714-104645_4000_battery.hdf5"
# srate = 4000
# fname = "20240714-121527_1000_usb.hdf5"
# srate = 1000
fname = "20240714-134022_1000_battery.hdf5"
srate = 1000

df = pd.read_hdf(fname, "eeg")
length = len(df)
start = df.index[0]
stop = df.index[-1]
duration = (stop - start).total_seconds()
rate = length / duration
drift = ((srate * 3600) - (rate * 3600)) / srate

print(f"File:\t\t{fname}")
print(f"Duration:\t{duration} seconds")
print(f"Nominal rate:\t{srate} Hz")
print(f"Actual rate:\t{rate} Hz")
print(f"Drift:\t\t{drift} seconds/hour")
