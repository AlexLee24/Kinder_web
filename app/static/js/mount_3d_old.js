/* =====================================================================
   3D Equatorial Mount Simulator  –  Pure WebGL (no library)
   =====================================================================
   Coordinate convention:
     RA  = rotation around polar axis   (0–360 deg)
     DEC = tilt of telescope tube around declination axis (-90 to +90 deg)
   The 3D model is built from simple geometric primitives.
   =================================================================== */

// ─── state ───────────────────────────────────────────────────────────
let currentRA  = 0;   // degrees
let currentDEC = 0;   // degrees
let targetRA   = 0;
let targetDEC  = 0;
let slewTimer  = null;
let slewAxis   = null;
let slewDir    = 0;

// camera orbit
let camTheta = 0.4;   // azimuth (rad)
let camPhi   = 0.3;   // elevation (rad)
let camDist  = 6.0;
let dragging = false;
let lastMouse = {x:0, y:0};

let gl, canvas;
let shaderProgram;
let uModel, uView, uProj, uColor;

// ─── helpers: degrees / radians ───────────────────────────────────────
const deg2rad = d => d * Math.PI / 180;
const rad2deg = r => r * 180 / Math.PI;

// ─── coordinate parsing ──────────────────────────────────────────────
function parseRA(str) {
    str = str.trim();
    // hh:mm:ss or hh mm ss
    const hms = str.match(/^(\d+)[:\s]+(\d+)[:\s]+([\d.]+)$/);
    if (hms) return (parseFloat(hms[1]) + parseFloat(hms[2])/60 + parseFloat(hms[3])/3600) * 15;
    const v = parseFloat(str);
    return isNaN(v) ? null : v;
}

function parseDEC(str) {
    str = str.trim();
    const dms = str.match(/^([+-]?\d+)[:\s]+(\d+)[:\s]+([\d.]+)$/);
    if (dms) {
        const sign = dms[1].startsWith('-') ? -1 : 1;
        return sign * (Math.abs(parseInt(dms[1])) + parseFloat(dms[2])/60 + parseFloat(dms[3])/3600);
    }
    const v = parseFloat(str);
    return isNaN(v) ? null : v;
}

function degToHMS(deg) {
    let h = deg / 15;
    if (h < 0) h += 24;
    const hh = Math.floor(h);
    const mm = Math.floor((h - hh) * 60);
    const ss = ((h - hh) * 60 - mm) * 60;
    return `${String(hh).padStart(2,'0')}h ${String(mm).padStart(2,'0')}m ${ss.toFixed(1)}s`;
}

function degToDMS(deg) {
    const sign = deg >= 0 ? '+' : '-';
    const abs = Math.abs(deg);
    const dd = Math.floor(abs);
    const mm = Math.floor((abs - dd) * 60);
    const ss = ((abs - dd) * 60 - mm) * 60;
    return `${sign}${String(dd).padStart(2,'0')}° ${String(mm).padStart(2,'0')}′ ${ss.toFixed(1)}″`;
}

// ─── WebGL setup ─────────────────────────────────────────────────────
const vsSource = `
    attribute vec3 aPos;
    attribute vec3 aNorm;
    uniform mat4 uModel;
    uniform mat4 uView;
    uniform mat4 uProj;
    varying vec3 vNorm;
    varying vec3 vWorldPos;
    void main(){
        vec4 world = uModel * vec4(aPos, 1.0);
        vWorldPos = world.xyz;
        vNorm = mat3(uModel) * aNorm;
        gl_Position = uProj * uView * world;
    }
`;

const fsSource = `
    precision mediump float;
    uniform vec3 uColor;
    varying vec3 vNorm;
    varying vec3 vWorldPos;
    void main(){
        vec3 lightDir = normalize(vec3(2.0, 5.0, 3.0));
        float diff = max(dot(normalize(vNorm), lightDir), 0.0);
        float amb = 0.25;
        vec3 col = uColor * (amb + diff * 0.75);
        gl_FragColor = vec4(col, 1.0);
    }
`;

function initGL() {
    canvas = document.getElementById('mount-canvas');
    gl = canvas.getContext('webgl', {antialias: true});
    if (!gl) { alert('WebGL not supported'); return; }

    resize();
    window.addEventListener('resize', resize);

    const vs = compileShader(gl.VERTEX_SHADER, vsSource);
    const fs = compileShader(gl.FRAGMENT_SHADER, fsSource);
    shaderProgram = gl.createProgram();
    gl.attachShader(shaderProgram, vs);
    gl.attachShader(shaderProgram, fs);
    gl.linkProgram(shaderProgram);
    gl.useProgram(shaderProgram);

    uModel = gl.getUniformLocation(shaderProgram, 'uModel');
    uView  = gl.getUniformLocation(shaderProgram, 'uView');
    uProj  = gl.getUniformLocation(shaderProgram, 'uProj');
    uColor = gl.getUniformLocation(shaderProgram, 'uColor');

    gl.enable(gl.DEPTH_TEST);
    gl.clearColor(0.04, 0.04, 0.08, 1);

    buildGeometry();
    setupMouseControls();
    requestAnimationFrame(renderLoop);
}

function compileShader(type, src) {
    const s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS))
        console.error(gl.getShaderInfoLog(s));
    return s;
}

function resize() {
    const parent = canvas.parentElement;
    canvas.width  = parent.clientWidth;
    canvas.height = parent.clientHeight;
    gl.viewport(0, 0, canvas.width, canvas.height);
}

// ─── geometry builders ───────────────────────────────────────────────
let meshes = {};

function createCylinder(r, h, seg) {
    seg = seg || 24;
    const pos = [], norm = [], idx = [];
    // side
    for (let i = 0; i <= seg; i++) {
        const a = (i / seg) * Math.PI * 2;
        const nx = Math.cos(a), nz = Math.sin(a);
        pos.push(r*nx, -h/2, r*nz,  r*nx, h/2, r*nz);
        norm.push(nx, 0, nz,  nx, 0, nz);
    }
    for (let i = 0; i < seg; i++) {
        const a = i*2, b = a+1, c = a+2, d = a+3;
        idx.push(a,b,c, b,d,c);
    }
    // caps
    const base = pos.length / 3;
    pos.push(0, h/2, 0); norm.push(0,1,0);
    for (let i = 0; i <= seg; i++) {
        const a = (i/seg)*Math.PI*2;
        pos.push(r*Math.cos(a), h/2, r*Math.sin(a));
        norm.push(0,1,0);
    }
    for (let i = 0; i < seg; i++) idx.push(base, base+1+i, base+2+i);

    const base2 = pos.length / 3;
    pos.push(0, -h/2, 0); norm.push(0,-1,0);
    for (let i = 0; i <= seg; i++) {
        const a = (i/seg)*Math.PI*2;
        pos.push(r*Math.cos(a), -h/2, r*Math.sin(a));
        norm.push(0,-1,0);
    }
    for (let i = 0; i < seg; i++) idx.push(base2, base2+2+i, base2+1+i);

    return uploadMesh(new Float32Array(pos), new Float32Array(norm), new Uint16Array(idx));
}

function createBox(sx, sy, sz) {
    const x=sx/2, y=sy/2, z=sz/2;
    const pos = [
        // front
        -x,-y,z, x,-y,z, x,y,z, -x,y,z,
        // back
        x,-y,-z, -x,-y,-z, -x,y,-z, x,y,-z,
        // top
        -x,y,z, x,y,z, x,y,-z, -x,y,-z,
        // bottom
        -x,-y,-z, x,-y,-z, x,-y,z, -x,-y,z,
        // right
        x,-y,z, x,-y,-z, x,y,-z, x,y,z,
        // left
        -x,-y,-z, -x,-y,z, -x,y,z, -x,y,-z,
    ];
    const norm = [
        0,0,1, 0,0,1, 0,0,1, 0,0,1,
        0,0,-1, 0,0,-1, 0,0,-1, 0,0,-1,
        0,1,0, 0,1,0, 0,1,0, 0,1,0,
        0,-1,0, 0,-1,0, 0,-1,0, 0,-1,0,
        1,0,0, 1,0,0, 1,0,0, 1,0,0,
        -1,0,0, -1,0,0, -1,0,0, -1,0,0,
    ];
    const idx = [];
    for (let i = 0; i < 6; i++) {
        const b = i*4;
        idx.push(b,b+1,b+2, b,b+2,b+3);
    }
    return uploadMesh(new Float32Array(pos), new Float32Array(norm), new Uint16Array(idx));
}

function uploadMesh(pos, norm, idx) {
    const vao = {};
    vao.posBuf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, vao.posBuf);
    gl.bufferData(gl.ARRAY_BUFFER, pos, gl.STATIC_DRAW);

    vao.normBuf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, vao.normBuf);
    gl.bufferData(gl.ARRAY_BUFFER, norm, gl.STATIC_DRAW);

    vao.idxBuf = gl.createBuffer();
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, vao.idxBuf);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, idx, gl.STATIC_DRAW);
    vao.count = idx.length;
    return vao;
}

function drawMesh(mesh, modelMat, color) {
    const aPos  = gl.getAttribLocation(shaderProgram, 'aPos');
    const aNorm = gl.getAttribLocation(shaderProgram, 'aNorm');

    gl.bindBuffer(gl.ARRAY_BUFFER, mesh.posBuf);
    gl.enableVertexAttribArray(aPos);
    gl.vertexAttribPointer(aPos, 3, gl.FLOAT, false, 0, 0);

    gl.bindBuffer(gl.ARRAY_BUFFER, mesh.normBuf);
    gl.enableVertexAttribArray(aNorm);
    gl.vertexAttribPointer(aNorm, 3, gl.FLOAT, false, 0, 0);

    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, mesh.idxBuf);

    gl.uniformMatrix4fv(uModel, false, modelMat);
    gl.uniform3fv(uColor, color);
    gl.drawElements(gl.TRIANGLES, mesh.count, gl.UNSIGNED_SHORT, 0);
}

function buildGeometry() {
    meshes.tripodLeg  = createBox(0.08, 1.6, 0.08);
    meshes.basePlate  = createCylinder(0.45, 0.12, 32);
    meshes.polarShaft = createCylinder(0.15, 1.4, 24);
    meshes.decHub     = createCylinder(0.22, 0.35, 24);
    meshes.decShaft   = createCylinder(0.10, 0.9, 20);
    meshes.tube       = createCylinder(0.14, 1.8, 24);
    meshes.cwBar      = createCylinder(0.04, 1.0, 12);
    meshes.cw         = createCylinder(0.18, 0.15, 24);
    meshes.finderTube = createCylinder(0.04, 0.6, 12);
}

// ─── matrix math ─────────────────────────────────────────────────────
function mat4Identity() { const m=new Float32Array(16); m[0]=m[5]=m[10]=m[15]=1; return m; }

function mat4Multiply(a, b) {
    const r = new Float32Array(16);
    for (let i=0;i<4;i++) for (let j=0;j<4;j++) {
        r[j*4+i] = a[i]*b[j*4] + a[4+i]*b[j*4+1] + a[8+i]*b[j*4+2] + a[12+i]*b[j*4+3];
    }
    return r;
}

function mat4Translate(x,y,z) {
    const m=mat4Identity(); m[12]=x; m[13]=y; m[14]=z; return m;
}

function mat4RotateX(a) {
    const m=mat4Identity(), c=Math.cos(a), s=Math.sin(a);
    m[5]=c; m[6]=s; m[9]=-s; m[10]=c; return m;
}

function mat4RotateY(a) {
    const m=mat4Identity(), c=Math.cos(a), s=Math.sin(a);
    m[0]=c; m[2]=-s; m[8]=s; m[10]=c; return m;
}

function mat4RotateZ(a) {
    const m=mat4Identity(), c=Math.cos(a), s=Math.sin(a);
    m[0]=c; m[1]=s; m[4]=-s; m[5]=c; return m;
}

function mat4Perspective(fov, aspect, near, far) {
    const f=1/Math.tan(fov/2), nf=1/(near-far), m=new Float32Array(16);
    m[0]=f/aspect; m[5]=f; m[10]=(far+near)*nf; m[11]=-1; m[14]=2*far*near*nf; return m;
}

function mat4LookAt(eye, center, up) {
    const zx=eye[0]-center[0], zy=eye[1]-center[1], zz=eye[2]-center[2];
    let len=Math.sqrt(zx*zx+zy*zy+zz*zz);
    const fz=[zx/len,zy/len,zz/len];
    const sx=up[1]*fz[2]-up[2]*fz[1], sy=up[2]*fz[0]-up[0]*fz[2], sz=up[0]*fz[1]-up[1]*fz[0];
    len=Math.sqrt(sx*sx+sy*sy+sz*sz);
    const fx=[sx/len,sy/len,sz/len];
    const ux=fz[1]*fx[2]-fz[2]*fx[1], uy=fz[2]*fx[0]-fz[0]*fx[2], uz=fz[0]*fx[1]-fz[1]*fx[0];
    const m=new Float32Array(16);
    m[0]=fx[0];m[1]=ux;m[2]=fz[0];m[3]=0;
    m[4]=fx[1];m[5]=uy;m[6]=fz[1];m[7]=0;
    m[8]=fx[2];m[9]=uz;m[10]=fz[2];m[11]=0;
    m[12]=-(fx[0]*eye[0]+fx[1]*eye[1]+fx[2]*eye[2]);
    m[13]=-(ux*eye[0]+uy*eye[1]+uz*eye[2]);
    m[14]=-(fz[0]*eye[0]+fz[1]*eye[1]+fz[2]*eye[2]);
    m[15]=1;
    return m;
}

// ─── mouse orbit camera ──────────────────────────────────────────────
function setupMouseControls() {
    canvas.addEventListener('mousedown', e => { dragging=true; lastMouse={x:e.clientX, y:e.clientY}; });
    window.addEventListener('mouseup', () => dragging=false);
    window.addEventListener('mousemove', e => {
        if (!dragging) return;
        const dx = e.clientX - lastMouse.x;
        const dy = e.clientY - lastMouse.y;
        camTheta -= dx * 0.005;
        camPhi   += dy * 0.005;
        camPhi = Math.max(-Math.PI/2.2, Math.min(Math.PI/2.2, camPhi));
        lastMouse = {x:e.clientX, y:e.clientY};
    });
    canvas.addEventListener('wheel', e => {
        e.preventDefault();
        camDist += e.deltaY * 0.005;
        camDist = Math.max(3, Math.min(15, camDist));
    }, {passive:false});
    // Touch support
    canvas.addEventListener('touchstart', e => {
        if (e.touches.length === 1) { dragging = true; lastMouse = {x: e.touches[0].clientX, y: e.touches[0].clientY}; }
    });
    canvas.addEventListener('touchend', () => dragging = false);
    canvas.addEventListener('touchmove', e => {
        if (!dragging || e.touches.length !== 1) return;
        e.preventDefault();
        const dx = e.touches[0].clientX - lastMouse.x;
        const dy = e.touches[0].clientY - lastMouse.y;
        camTheta -= dx * 0.005;
        camPhi   += dy * 0.005;
        camPhi = Math.max(-Math.PI/2.2, Math.min(Math.PI/2.2, camPhi));
        lastMouse = {x: e.touches[0].clientX, y: e.touches[0].clientY};
    }, {passive: false});
}

// ─── render ──────────────────────────────────────────────────────────
const COLORS = {
    tripod:  [0.25, 0.25, 0.28],
    base:    [0.35, 0.35, 0.38],
    polar:   [0.30, 0.30, 0.33],
    decHub:  [0.40, 0.36, 0.28],
    tube:    [0.85, 0.85, 0.90],
    cw:      [0.50, 0.50, 0.55],
    cwBar:   [0.30, 0.30, 0.33],
    finder:  [0.6, 0.6, 0.65],
};

// Latitude of observation site (Lulin Observatory ~ 23.47°N)
const LATITUDE = 23.47;

function renderLoop() {
    requestAnimationFrame(renderLoop);
    resize();
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

    // Camera
    const eyeX = camDist * Math.cos(camPhi) * Math.sin(camTheta);
    const eyeY = camDist * Math.sin(camPhi) + 1.5;
    const eyeZ = camDist * Math.cos(camPhi) * Math.cos(camTheta);
    const view = mat4LookAt([eyeX, eyeY, eyeZ], [0, 1.2, 0], [0, 1, 0]);
    const proj = mat4Perspective(deg2rad(45), canvas.width/canvas.height, 0.1, 100);
    gl.uniformMatrix4fv(uView, false, view);
    gl.uniformMatrix4fv(uProj, false, proj);

    const raRad  = deg2rad(currentRA);
    const decRad = deg2rad(currentDEC);
    const latRad = deg2rad(LATITUDE);

    // ─── Draw Tripod ───
    const legAngles = [0, 120, 240];
    for (const la of legAngles) {
        const a = deg2rad(la);
        let m = mat4Translate(0.35*Math.sin(a), 0.7, 0.35*Math.cos(a));
        m = mat4Multiply(m, mat4RotateZ(deg2rad(la === 120 ? 8 : la === 240 ? -8 : 0)));
        m = mat4Multiply(m, mat4RotateX(la === 0 ? deg2rad(-6): la === 120 ? deg2rad(3) : deg2rad(3)));
        drawMesh(meshes.tripodLeg, m, COLORS.tripod);
    }

    // ─── Base plate (top of tripod) ───
    const baseM = mat4Translate(0, 1.55, 0);
    drawMesh(meshes.basePlate, baseM, COLORS.base);

    // ─── Polar axis (tilted at latitude) ───
    // Tilt the entire polar assembly by latitude angle
    let polarBase = mat4Translate(0, 1.65, 0);
    polarBase = mat4Multiply(polarBase, mat4RotateX(-latRad));
    // Rotate by RA around polar axis (Y in polar frame)
    let polarRA = mat4Multiply(polarBase, mat4RotateY(raRad));

    // Draw polar shaft
    let polarM = mat4Multiply(polarRA, mat4Translate(0, 0.7, 0));
    drawMesh(meshes.polarShaft, polarM, COLORS.polar);

    // ─── DEC hub at top of polar shaft ───
    let decHubBase = mat4Multiply(polarRA, mat4Translate(0, 1.42, 0));
    drawMesh(meshes.decHub, decHubBase, COLORS.decHub);

    // ─── DEC rotation: rotate around axis perpendicular to polar ───
    let decBase = mat4Multiply(decHubBase, mat4RotateZ(decRad));

    // ─── Telescope tube ───
    let tubeM = mat4Multiply(decBase, mat4Translate(0, 0.95, 0));
    drawMesh(meshes.tube, tubeM, COLORS.tube);

    // ─── Finder scope ───
    let finderM = mat4Multiply(decBase, mat4Translate(0.2, 0.8, 0));
    drawMesh(meshes.finderTube, finderM, COLORS.finder);

    // ─── Counterweight bar (opposite to tube) ───
    let cwBarM = mat4Multiply(decBase, mat4Translate(0, -0.5, 0));
    drawMesh(meshes.cwBar, cwBarM, COLORS.cwBar);

    // ─── Counterweight ───
    let cwM = mat4Multiply(decBase, mat4Translate(0, -0.9, 0));
    drawMesh(meshes.cw, cwM, COLORS.cw);

    // Update HUD
    updatePositionDisplay();
}

// ─── position display ────────────────────────────────────────────────
function updatePositionDisplay() {
    const ra  = ((currentRA % 360) + 360) % 360;
    const dec = Math.max(-90, Math.min(90, currentDEC));

    document.getElementById('info-ra').textContent  = ra.toFixed(2);
    document.getElementById('info-dec').textContent = dec.toFixed(2);
    document.getElementById('pos-ra-deg').textContent  = ra.toFixed(3) + '°';
    document.getElementById('pos-dec-deg').textContent = dec.toFixed(3) + '°';
    document.getElementById('pos-ra-hms').textContent  = degToHMS(ra);
    document.getElementById('pos-dec-dms').textContent = degToDMS(dec);
}

// ─── slewing (smooth animation) ──────────────────────────────────────
let animating = false;
let animRA_start, animDEC_start, animRA_end, animDEC_end, animStart, animDur;

function animateTo(ra, dec) {
    targetRA  = ((ra % 360) + 360) % 360;
    targetDEC = Math.max(-90, Math.min(90, dec));
    animRA_start  = currentRA;
    animDEC_start = currentDEC;
    animRA_end  = targetRA;
    animDEC_end = targetDEC;

    // Choose shortest RA path
    let dRA = animRA_end - animRA_start;
    if (dRA > 180) dRA -= 360;
    if (dRA < -180) dRA += 360;
    animRA_end = animRA_start + dRA;

    const dist = Math.sqrt(dRA*dRA + (animDEC_end - animDEC_start)**2);
    const speed = parseFloat(document.getElementById('slew-speed').value) || 10;
    animDur = Math.max(300, (dist / speed) * 1000);
    animStart = performance.now();
    animating = true;
    requestAnimationFrame(animStep);
}

function animStep(ts) {
    if (!animating) return;
    let t = (ts - animStart) / animDur;
    if (t >= 1) { t = 1; animating = false; }
    // Ease in-out
    t = t < 0.5 ? 2*t*t : -1 + (4 - 2*t)*t;
    currentRA  = animRA_start  + (animRA_end  - animRA_start)  * t;
    currentDEC = animDEC_start + (animDEC_end - animDEC_start) * t;
    currentRA = ((currentRA % 360) + 360) % 360;
    if (animating) requestAnimationFrame(animStep);
}

// ─── manual slew (hold button) ───────────────────────────────────────
function startSlew(axis, dir) {
    slewAxis = axis;
    slewDir  = dir;
    if (slewTimer) return;
    const step = () => {
        const speed = parseFloat(document.getElementById('slew-speed').value) || 10;
        const delta = speed * 0.03;  // per frame
        if (slewAxis === 'ra') {
            currentRA += slewDir * delta;
            currentRA = ((currentRA % 360) + 360) % 360;
        } else {
            currentDEC += slewDir * delta;
            currentDEC = Math.max(-90, Math.min(90, currentDEC));
        }
        slewTimer = requestAnimationFrame(step);
    };
    slewTimer = requestAnimationFrame(step);
}

function stopSlew() {
    if (slewTimer) cancelAnimationFrame(slewTimer);
    slewTimer = null;
}

// ─── coordinate goto ─────────────────────────────────────────────────
function gotoCoordinate() {
    const raStr  = document.getElementById('input-ra').value;
    const decStr = document.getElementById('input-dec').value;
    const ra  = parseRA(raStr);
    const dec = parseDEC(decStr);
    if (ra === null) { alert('Invalid RA format. Use hh:mm:ss or degrees.'); return; }
    if (dec === null) { alert('Invalid DEC format. Use ±dd:mm:ss or degrees.'); return; }
    animateTo(ra, dec);
}

function gotoPreset(ra, dec) {
    animateTo(ra, dec);
}

function updateSpeedLabel() {
    document.getElementById('speed-label').textContent = document.getElementById('slew-speed').value + '°/s';
}

// ─── init ────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', initGL);
