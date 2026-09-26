"""Convert the TF ESPCN super-resolution models (github.com/fannymonori/TF-ESPCN) to ONNX,
because OpenCV's TensorFlow importer can't handle their DepthToSpace layer."""
import cv2, numpy as np, onnx, sys
MODE = sys.argv[1] if len(sys.argv) > 1 else 'DCR'
from onnx import helper, numpy_helper, TensorProto
for s in (2, 3, 4):
    n = cv2.dnn.readNetFromTensorflow(f'ESPCN_x{s}.pb')
    blob = lambda name: n.getLayer(n.getLayerId(name)).blobs[0]
    inits, nodes, prev = [], [], 'input'
    for i, (conv, add, pad) in enumerate((('conv1', 'add', 2), ('conv2', 'add_1', 1), ('conv3', 'add_2', 1))):
        W, b = blob(conv).astype(np.float32), blob(add).reshape(-1).astype(np.float32)
        inits += [numpy_helper.from_array(W, f'W{i}'), numpy_helper.from_array(b, f'B{i}')]
        nodes.append(helper.make_node('Conv', [prev, f'W{i}', f'B{i}'], [f'c{i}'], pads=[pad] * 4, kernel_shape=list(W.shape[2:])))
        prev = f'c{i}'
        if i < 2:
            nodes.append(helper.make_node('Relu', [prev], [f'r{i}'])); prev = f'r{i}'
    nodes.append(helper.make_node('DepthToSpace', [prev], ['d2s'], blocksize=s, mode=MODE))
    nodes.append(helper.make_node('Tanh', ['d2s'], ['output']))   # the TF graph's 'NHWC_output' node
    g = helper.make_graph(nodes, f'espcn_x{s}',
                          [helper.make_tensor_value_info('input', TensorProto.FLOAT, [1, 1, 'h', 'w'])],
                          [helper.make_tensor_value_info('output', TensorProto.FLOAT, [1, 1, 'H', 'W'])], inits)
    m = helper.make_model(g, opset_imports=[helper.make_opsetid('', 13)]); m.ir_version = 8
    onnx.checker.check_model(m); onnx.save(m, f'ESPCN_x{s}.onnx'); print('wrote', f'ESPCN_x{s}.onnx')
