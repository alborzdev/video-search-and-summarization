# East pedestrian episode: camera journey forensic

The native story completed in **81.520 wall seconds**, but the camera had no
continuous same-ID traversal from one end to the other. The zero completed count
was therefore correct for the retained observations. See the
[exact receipt](pedestrian-east-v3-forensic.json).

The CPU replay used 2,298 real native observation rows, including 1,149 southwest
frames, with the same person homography, three East polygons and current
MobilitySpatial implementation. It started 20 seconds before the UI observer.
Earlier live history is excluded from replay totals. No actor ground truth
entered camera analytics.

North-origin local handle `5527462707671859204` entered the crossing at source
time `1793003197509030111`. About 386 ms later, its exported first-stage NvDCF
rectangle grew from roughly 29 to 44 pixels high. The projected point moved
from (-11.131,85.317) to (-13.345,83.220) across the west side in 191 ms. It
returned inside 54 ms later. The side exit ended the journey as incomplete; a
side re-entry cannot create a new valid end-to-end journey. The run did not
retain separate raw detector and tracker boxes, so this evidence does not
establish which stage caused the rectangle outlier.

A second person entered from the south. Around observer seconds 62–64, the two
handle paths reversed near their meeting. The north-origin handle then moved
north, while south-origin `5527462707671859206` moved south and was recorded as
returned. The separately saved leased native actor continued south. This is
strong evidence of an association swap. The saved UI images show both people
in the strip; they are not a matched image sequence that proves each exact
assignment at the meeting. Both relevant handles stayed within the existing
one-second observation-gap limit during observer seconds 42–78.

The bounded source response has two parts: reserve the next normal crossing
cohort for the owned person while it waits at the verified curb, and treat a
single unconfirmed outside measurement as pending exit evidence. An earlier
normal crossing can finish. Current WALK, native path and signal checks remain
in force. Raw outside positions and visible occupancy remain truthful. Neither
change can recover a lost identity, use simulator positions as observations or
count an unobserved far-side exit. Live acceptance is separate.
