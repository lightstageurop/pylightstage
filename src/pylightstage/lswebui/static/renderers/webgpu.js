const SHADER = /* wgsl */ `
struct Camera {
  viewProjection: mat4x4<f32>,
  position: vec4<f32>,
}

@group(0) @binding(0) var<uniform> camera: Camera;

struct VertexOutput {
  @builtin(position) position: vec4<f32>,
  @location(0) worldPosition: vec3<f32>,
  @location(1) normal: vec3<f32>,
  @location(2) colour: vec4<f32>,
}

@vertex
fn vertex_main(
  @location(0) vertexPosition: vec3<f32>,
  @location(1) normal: vec3<f32>,
  @location(2) instancePosition: vec3<f32>,
  @location(3) instanceRight: vec3<f32>,
  @location(4) instanceUp: vec3<f32>,
  @location(5) instanceColour: vec4<f32>,
) -> VertexOutput {
  var output: VertexOutput;
  let forward = normalize(cross(instanceUp, instanceRight));
  let worldPosition = instancePosition
    + instanceRight * vertexPosition.x
    + instanceUp * vertexPosition.y
    + forward * vertexPosition.z;
  output.position = camera.viewProjection * vec4<f32>(worldPosition, 1.0);
  output.worldPosition = worldPosition;
  output.normal = normalize(
    instanceRight * normal.x + instanceUp * normal.y + forward * normal.z
  );
  output.colour = instanceColour;
  return output;
}

@fragment
fn fragment_main(input: VertexOutput) -> @location(0) vec4<f32> {
  if (input.colour.a < 0.5) { discard; }
  let toCamera = normalize(camera.position.xyz - input.worldPosition);
  let keyLight = normalize(vec3<f32>(-0.45, 0.85, 0.65));
  let diffuse = max(dot(normalize(input.normal), keyLight), 0.0);
  let rim = pow(1.0 - max(dot(normalize(input.normal), toCamera), 0.0), 2.0);
  let luminance = max(max(input.colour.r, input.colour.g), input.colour.b);
  let emissive = input.colour.rgb * (0.52 + luminance * 0.68);
  let surface = input.colour.rgb * (0.3 + diffuse * 0.62) + vec3<f32>(0.06, 0.09, 0.09) * rim;
  let selected = step(1.5, input.colour.a);
  let selection = vec3<f32>(0.08, 0.42, 0.34) * selected * (0.3 + rim * 0.8);
  return vec4<f32>(max(surface, emissive) + selection, 1.0);
}
`;

function cylinderVertices(segments = 18, radius = 0.052, halfDepth = 0.026) {
  const values = [];
  for (let index = 0; index < segments; index += 1) {
    const angleA = (index / segments) * Math.PI * 2;
    const angleB = ((index + 1) / segments) * Math.PI * 2;
    const a = [Math.cos(angleA) * radius, Math.sin(angleA) * radius];
    const b = [Math.cos(angleB) * radius, Math.sin(angleB) * radius];
    const sideA = [Math.cos(angleA), Math.sin(angleA), 0];
    const sideB = [Math.cos(angleB), Math.sin(angleB), 0];

    // Side wall.
    values.push(...a, -halfDepth, ...sideA, ...b, -halfDepth, ...sideB, ...b, halfDepth, ...sideB);
    values.push(...a, -halfDepth, ...sideA, ...b, halfDepth, ...sideB, ...a, halfDepth, ...sideA);
    // Front and rear caps.
    values.push(0, 0, halfDepth, 0, 0, 1, ...a, halfDepth, 0, 0, 1, ...b, halfDepth, 0, 0, 1);
    values.push(0, 0, -halfDepth, 0, 0, -1, ...b, -halfDepth, 0, 0, -1, ...a, -halfDepth, 0, 0, -1);
  }
  return new Float32Array(values);
}

function perspective(fov, aspect, near, far) {
  const f = 1 / Math.tan(fov / 2);
  const range = 1 / (near - far);
  return new Float32Array([
    f / aspect, 0, 0, 0,
    0, f, 0, 0,
    0, 0, far * range, -1,
    0, 0, near * far * range, 0,
  ]);
}

function lookAt(eye, target, up) {
  const normalize = ([x, y, z]) => {
    const length = Math.hypot(x, y, z) || 1;
    return [x / length, y / length, z / length];
  };
  const z = normalize([eye[0] - target[0], eye[1] - target[1], eye[2] - target[2]]);
  const x = normalize([
    up[1] * z[2] - up[2] * z[1],
    up[2] * z[0] - up[0] * z[2],
    up[0] * z[1] - up[1] * z[0],
  ]);
  const y = [
    z[1] * x[2] - z[2] * x[1],
    z[2] * x[0] - z[0] * x[2],
    z[0] * x[1] - z[1] * x[0],
  ];
  return new Float32Array([
    x[0], y[0], z[0], 0,
    x[1], y[1], z[1], 0,
    x[2], y[2], z[2], 0,
    -(x[0] * eye[0] + x[1] * eye[1] + x[2] * eye[2]),
    -(y[0] * eye[0] + y[1] * eye[1] + y[2] * eye[2]),
    -(z[0] * eye[0] + z[1] * eye[1] + z[2] * eye[2]),
    1,
  ]);
}

function multiply(a, b) {
  const out = new Float32Array(16);
  for (let column = 0; column < 4; column += 1) {
    for (let row = 0; row < 4; row += 1) {
      let value = 0;
      for (let index = 0; index < 4; index += 1) value += a[index * 4 + row] * b[column * 4 + index];
      out[column * 4 + row] = value;
    }
  }
  return out;
}

export class WebGPURenderer {
  static async create(canvas) {
    if (!navigator.gpu) throw new Error("WebGPU is not available in this browser");
    const adapter = await navigator.gpu.requestAdapter({ powerPreference: "high-performance" });
    if (!adapter) throw new Error("No compatible WebGPU adapter was found");
    const device = await adapter.requestDevice();
    const context = canvas.getContext("webgpu");
    if (!context) throw new Error("Could not create a WebGPU canvas context");
    return new WebGPURenderer(canvas, device, context);
  }

  constructor(canvas, device, context) {
    this.canvas = canvas;
    this.device = device;
    this.context = context;
    this.format = navigator.gpu.getPreferredCanvasFormat();
    this.depthTexture = null;
    this.uploadedVersion = -1;

    const vertices = cylinderVertices();
    this.vertexCount = vertices.length / 6;
    this.vertexBuffer = device.createBuffer({
      label: "fixture cylinder geometry",
      size: vertices.byteLength,
      usage: GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST,
    });
    device.queue.writeBuffer(this.vertexBuffer, 0, vertices);

    this.instanceBuffer = device.createBuffer({
      label: "paired fixture instances",
      size: 336 * 16 * Float32Array.BYTES_PER_ELEMENT,
      usage: GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST,
    });
    this.cameraBuffer = device.createBuffer({
      label: "orbit camera",
      size: 80,
      usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
    });
    const shader = device.createShaderModule({ label: "stage fixture cylinders", code: SHADER });
    this.pipeline = device.createRenderPipeline({
      label: "stage fixture pipeline",
      layout: "auto",
      vertex: {
        module: shader,
        entryPoint: "vertex_main",
        buffers: [
          {
            arrayStride: 24,
            attributes: [
              { shaderLocation: 0, offset: 0, format: "float32x3" },
              { shaderLocation: 1, offset: 12, format: "float32x3" },
            ],
          },
          {
            arrayStride: 64,
            stepMode: "instance",
            attributes: [
              { shaderLocation: 2, offset: 0, format: "float32x3" },
              { shaderLocation: 3, offset: 16, format: "float32x3" },
              { shaderLocation: 4, offset: 32, format: "float32x3" },
              { shaderLocation: 5, offset: 48, format: "float32x4" },
            ],
          },
        ],
      },
      fragment: { module: shader, entryPoint: "fragment_main", targets: [{ format: this.format }] },
      primitive: { topology: "triangle-list", cullMode: "back" },
      depthStencil: { format: "depth24plus", depthWriteEnabled: true, depthCompare: "less" },
    });
    this.bindGroup = device.createBindGroup({
      layout: this.pipeline.getBindGroupLayout(0),
      entries: [{ binding: 0, resource: { buffer: this.cameraBuffer } }],
    });
    context.configure({ device, format: this.format, alphaMode: "opaque" });
  }

  resize() {
    const scale = Math.min(window.devicePixelRatio || 1, 2);
    const width = Math.max(1, Math.floor(this.canvas.clientWidth * scale));
    const height = Math.max(1, Math.floor(this.canvas.clientHeight * scale));
    const sizeChanged = this.canvas.width !== width || this.canvas.height !== height;
    if (!sizeChanged && this.depthTexture) return;
    if (sizeChanged) {
      this.canvas.width = width;
      this.canvas.height = height;
    }
    this.depthTexture?.destroy();
    this.depthTexture = this.device.createTexture({
      size: [width, height],
      format: "depth24plus",
      usage: GPUTextureUsage.RENDER_ATTACHMENT,
    });
  }

  render(scene, camera) {
    this.resize();
    if (!this.depthTexture) return;
    if (this.uploadedVersion !== scene.version) {
      this.device.queue.writeBuffer(this.instanceBuffer, 0, scene.instanceData);
      this.uploadedVersion = scene.version;
    }
    const horizontalDistance = Math.cos(camera.pitch) * camera.distance;
    const eye = [
      Math.sin(camera.yaw) * horizontalDistance,
      Math.sin(camera.pitch) * camera.distance,
      Math.cos(camera.yaw) * horizontalDistance,
    ];
    const projection = perspective(Math.PI / 3.15, this.canvas.width / this.canvas.height, 0.05, 20);
    const viewProjection = multiply(projection, lookAt(eye, [0, 0, 0], [0, 1, 0]));
    this.device.queue.writeBuffer(this.cameraBuffer, 0, viewProjection);
    this.device.queue.writeBuffer(this.cameraBuffer, 64, new Float32Array([...eye, 1]));

    const encoder = this.device.createCommandEncoder({ label: "stage frame" });
    const pass = encoder.beginRenderPass({
      colorAttachments: [{
        view: this.context.getCurrentTexture().createView(),
        clearValue: { r: 0.018, g: 0.032, b: 0.034, a: 1 },
        loadOp: "clear",
        storeOp: "store",
      }],
      depthStencilAttachment: {
        view: this.depthTexture.createView(),
        depthClearValue: 1,
        depthLoadOp: "clear",
        depthStoreOp: "store",
      },
    });
    pass.setPipeline(this.pipeline);
    pass.setBindGroup(0, this.bindGroup);
    pass.setVertexBuffer(0, this.vertexBuffer);
    pass.setVertexBuffer(1, this.instanceBuffer);
    pass.draw(this.vertexCount, scene.count);
    pass.end();
    this.device.queue.submit([encoder.finish()]);
  }
}
