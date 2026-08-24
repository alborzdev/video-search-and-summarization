// SPDX-License-Identifier: MIT
import { metricValue } from '../../../pages/api/vision/health';

describe('Thor health metrics', () => {
  const metrics = [
    'jetson_tegrastats_up 1',
    'jetson_tegrastats_temperature_celsius{zone="gpu"} 41.5',
    'jetson_tegrastats_power_milliwatts{rail="VDD_GPU",aggregation="current"} 3270',
    'jetson_tegrastats_ram_used_bytes 1.234e+10',
  ].join('\n');

  it('reads both bare and labelled Prometheus measurements', () => {
    expect(metricValue(metrics, 'jetson_tegrastats_up')).toBe(1);
    expect(metricValue(metrics, 'jetson_tegrastats_temperature_celsius', '\\{zone="gpu"\\}')).toBe(41.5);
    expect(metricValue(metrics, 'jetson_tegrastats_power_milliwatts', '\\{rail="VDD_GPU",aggregation="current"\\}')).toBe(3270);
    expect(metricValue(metrics, 'jetson_tegrastats_ram_used_bytes')).toBe(1.234e10);
  });

  it('returns null when a measurement is unavailable', () => {
    expect(metricValue(metrics, 'jetson_tegrastats_gpu_utilization_ratio')).toBeNull();
  });
});
