# Evidence

The 2026-08-11 Thor run passed all 15 VIOS requests against VSS 3.2.1. A
40,394-byte H.264/AAC fixture uploaded and registered with stable file, sensor,
and stream identifiers; the exact source bytes downloaded with SHA-256
`4985870a996fbd112ed0bc9d727f6f44b43b2d0f3c6bfc700f8a6bbffeacafa2`.
The adjacent duplicate-name upload returned HTTP 409.

The executor derived an interior interval from the returned runtime timeline.
VIOS produced a distinct 58,223-byte, 1.2-second H.264 MP4 clip. A historical
snapshot at the returned start timestamp was a decodable 4,152-byte,
160x120 MJPEG image. Its decoded RGB mean absolute error against the owned
source marker was 15.611770833333333, below the locked maximum of 20.

Cleanup removed the owned media and sensor and restored the exact pre-run file
and sensor inventories. No raw identifiers, request paths, media, or unrelated
inventory contents are retained. The run made no VSS Agent, RT-CV stream, or
Warehouse sample call.

Artifact locks:

- contract: `59a47ef278c025d3ed043e8c29e0ac311fe96beddcc484419411c92f9b01d6ba`
- receipt schema: `cfeba358a935038f71272981ed51081ba459bdca8c57a304154b782840cf242b`
- runtime receipt: `9db571f5a0602e4db6b60edda81f831e680cfa08e337aefa8e6bb2906f95fba3`
- executor: `8c2c04cadb969d545ae508ec881305b832d4796cc50f181151e99a8069426b34`
