# Nokia 5110 text behavior

The 84x48 screen uses bounded drawing regions so one string cannot overwrite another field.

The status page has five fixed rows. Printing state is host-independent and long SD filenames use a UTF-8-aware status marquee. Idle MPU information shows startup level first when available, then calibrated IMU die temperature. During printing the footer can alternate Z/progress with live vibration RMS/peak.

## Menu labels

A long plain menu label scrolls only while selected. It waits 900 ms, then advances one UTF-8 character every 420 ms inside the label's existing viewport. At the end it pauses for one second and restarts. The submenu arrow stays fixed.

Editable labels use the same behavior but their viewport ends before the colon/value field, so the numeric or boolean value never moves or gets overwritten.

Labels that contain Marlin dynamic substitution tokens use the native renderer instead of the marquee.
