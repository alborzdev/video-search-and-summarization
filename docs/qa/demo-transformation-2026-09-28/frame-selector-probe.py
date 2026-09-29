"""Read-only sampler probe. Run inside vss-memory-cosmos with python3; no GPU imports."""
import ast
import logging
from collections import deque
from pathlib import Path
from types import SimpleNamespace

path = Path('/opt/nvidia/rtvi/rtvi/vlm_pipeline/video_file_frame_getter.py')
selector_class = next(node for node in ast.parse(path.read_text()).body
                      if isinstance(node, ast.ClassDef) and node.name == 'DefaultFrameSelector')
namespace = {'deque': deque, 'ChunkInfo': object, 'logger': logging.getLogger('probe')}
exec(compile(ast.Module(body=[selector_class], type_ignores=[]), str(path), 'exec'), namespace)
selector = namespace['DefaultFrameSelector'](10)
selector.set_chunk(SimpleNamespace(start_pts=0, end_pts=5_000_000_000,
                                   pts_offset_ns=0, file='fixture'))
selected = [index / 10 for index in range(50)
            if selector.choose_frame(None, index * 100_000_000)]
print({'last_decoded_time': 4.9, 'selected_times': selected,
       'includes_final_frame': 4.9 in selected})
assert 4.9 in selected, 'Last decoded frame omitted by fixed-count sampler'
