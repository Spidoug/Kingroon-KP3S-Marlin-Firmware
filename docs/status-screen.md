# Nokia 5110 text behavior

The 84x48 screen uses bounded drawing regions so one string cannot overwrite another field.

During printing the footer is reserved for file name, Z position and progress; the MPU subsystem remains suspended.

## Menu labels

A long plain menu label scrolls only while selected. It waits 900 ms, then advances one UTF-8 character every 420 ms inside the label's existing viewport. At the end it pauses for one second and restarts. The submenu arrow stays fixed.

Editable labels use the same behavior but their viewport ends before the colon/value field, so the numeric or boolean value never moves or gets overwritten.

Labels that contain Marlin dynamic substitution tokens use the native renderer instead of the marquee.
