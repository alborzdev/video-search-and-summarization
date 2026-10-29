// SPDX-License-Identifier: MIT
import type { CityRule, CitySite, CitySource, Point } from './types';
import { objectName } from './geometry';
import intersectionBackdrop from './intersectionMapBackdrop.json';

/** The raster's footprint can extend beyond the operational/calibrated map.
 * Keep the default view, camera calibration and observation bounds untouched.
 */
export function mapBackdrop(site: CitySite) {
  const imageUrl = site.map.imageUrl;
  if (!imageUrl || !/^\/smart-city\/[A-Za-z0-9][A-Za-z0-9._-]*\.(png|jpe?g|webp)$/.test(imageUrl)) return null;
  const wide = site.id === intersectionBackdrop.siteId && imageUrl === intersectionBackdrop.replacesImageUrl
    && site.map.bounds.every((value, index) => value === intersectionBackdrop.focusBounds[index]);
  const bounds = wide ? intersectionBackdrop.bounds : site.map.bounds;
  return { imageUrl: wide ? intersectionBackdrop.imageUrl : imageUrl, bounds,
    minimumZoom: wide ? Math.min(.5, Math.max((site.map.bounds[2] - site.map.bounds[0]) / (bounds[2] - bounds[0]),
      (site.map.bounds[3] - site.map.bounds[1]) / (bounds[3] - bounds[1]))) : .5 };
}

/** Short direction cue, not a claimed detection range. The full footprint stays unchanged. */
export function cameraViewCue(source: CitySource, radius: number) {
  const eye = source.cameraPositionWorldM; const coverage = source.groundCoverageM;
  if (!source.calibrationRevision || !source.imageToGroundHomography || !eye || eye.length !== 3 || !eye.every(Number.isFinite)
    || !coverage || coverage.length < 3 || coverage.some(point => point.length !== 2 || !point.every(Number.isFinite))) return null;
  const origin: Point = [eye[0], eye[1]];
  const center: Point = [coverage.reduce((sum, point) => sum + point[0], 0) / coverage.length, coverage.reduce((sum, point) => sum + point[1], 0) / coverage.length];
  const forward = source.T_cv_from_site?.[2];
  const heading = forward && Number.isFinite(forward[0]) && Number.isFinite(forward[1]) && Math.hypot(forward[0], forward[1]) > 1e-6
    ? Math.atan2(forward[1], forward[0]) : Math.atan2(center[1] - origin[1], center[0] - origin[0]);
  const offsets = coverage.map(point => { const angle = Math.atan2(point[1] - origin[1], point[0] - origin[0]) - heading; return Math.atan2(Math.sin(angle), Math.cos(angle)); });
  const low = Math.min(...offsets); const high = Math.max(...offsets);
  // A footprint surrounding the camera has no single readable directional fan.
  const cone: Point[] = high - low < Math.PI ? [origin, ...Array.from({ length: 25 }, (_, index): Point => {
    const angle = heading + low + (high - low) * index / 24;
    return [origin[0] + Math.cos(angle) * radius, origin[1] + Math.sin(angle) * radius];
  })] : [];
  return { origin, center, heading, coverage, cone };
}

export function monitoringDescription(rule: CityRule): string {
  const classes = rule.classes.map(value => value === 'person' ? 'people' : `${objectName(value).toLowerCase()}${value === 'bus' ? 'es' : 's'}`);
  const subject = classes.length > 2 ? `${classes.slice(0, -1).join(', ')} and ${classes.at(-1)}` : classes.join(' and ') || 'objects';
  const seconds = (rule.conditions?.minimumDurationMs ?? 0) / 1000;
  switch (rule.kind) {
    case 'line-crossing': return `Counts ${subject} that cross this line in the configured direction.`;
    case 'occupancy-threshold': return `Counts ${subject} inside this area.`;
    case 'stopped-in-zone': return `Checks for ${subject} stopped in this area${seconds ? ` for at least ${seconds} seconds` : ''}.`;
    case 'queue': return `Measures slow or stopped ${subject} and the observed queue in this approach.`;
    case 'dwell': return `Checks how long ${subject} stay in this area${seconds ? `; the threshold is ${seconds} seconds` : ''}.`;
    case 'wrong-way': return `Checks for ${subject} moving against the configured direction.`;
    case 'area-entry': return `Detects ${subject} entering this area.`;
    default: return `Monitors ${subject} in this area.`;
  }
}
