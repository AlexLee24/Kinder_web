/* =====================================================================
   3D Equatorial Mount Simulator  –  Pure WebGL (no library)
   =====================================================================
   Coordinate convention:
     RA  = Celestial Right Ascension
     DEC = Celestial Declination
     HA  = Mechanical Hour Angle (Controls RA axis rotation)
     LST = Local Sidereal Time (Simulated)
   =================================================================== */

// ─── state ───────────────────────────────────────────────────────────
const SIDEREAL_RATE = 360 / 86164.0905; // degrees per second
let LST = 0; // Simulated Local Sidereal Time

let currentHA  = 0;   // Mechanical HA (0 = Home/Meridian)
let currentDEC = 90;  // Mechanical DEC (90 = Home/NCP)

let isTracking = false;
let animMode = 'none'; // 'celestial', 'mechanical', or 'none'
let animRA_start, animRA_end;
let animHA_start, animHA_end;
let animDEC_start, animDEC_end;
let animStart, animDur;

let slewTimer  = null;
let slewAxis   = null;
let slewDir    = 0;

// camera orbit
let camTheta = 0.6;   
let camPhi   = 0.35;  
let camDist  = 4.5;
let dragging = false;
let lastMouse = {x:0, y:0};

let gl, canvas;
let shaderProgram;
let uModel, uView, uProj, uColor;
let lastTimestamp = performance.now();

// Latitude of observation site
const LATITUDE = 23.5; 

// ─── helpers: degrees / radians ───────────────────────────────────────
const deg2rad = d => d * Math.PI / 180;
const rad2deg = r => r * 180 / Math.PI;

// ─── coordinate parsing ──────────────────────────────────────────────
function parseRA(str) {
    str = str.trim();
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
        vec3 n = normalize(vNorm);
        vec3 L1 = normalize(vec3(3.0, 5.0, 4.0));
        float diff1 = max(dot(n, L1), 0.0);
        vec3 L2 = normalize(vec3(-2.0, 3.0, -2.0));
        float diff2 = max(dot(n, L2), 0.0);
        vec3 viewDir = normalize(vec3(0.0, 3.0, 5.0) - vWorldPos);
        vec3 halfDir = normalize(L1 + viewDir);
        float spec = pow(max(dot(n, halfDir), 0.0), 32.0);
        float amb = 0.2;
        vec3 col = uColor * (amb + diff1 * 0.6 + diff2 * 0.2) + vec3(spec * 0.3);
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
    gl.clearColor(0.05, 0.05, 0.08, 1);

    buildGeometry();
    setupMouseControls();
    
    // Override 'Home / Park' button gracefully
    const presetBtns = document.querySelectorAll('.preset-btn');
    presetBtns.forEach(btn => {
        if (btn.textContent.includes('Home') || btn.textContent.includes('Park')) {
            btn.onclick = (e) => {
                e.preventDefault();
                parkMount();
            };
        }
    });

    requestAnimationFrame(renderLoop);
}

function compileShader(type, src) {
    const s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);
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
    seg = seg || 32;
    const pos = [], norm = [], idx = [];
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
        -x,-y,z, x,-y,z, x,y,z, -x,y,z,
        x,-y,-z, -x,-y,-z, -x,y,-z, x,y,-z,
        -x,y,z, x,y,z, x,y,-z, -x,y,-z,
        -x,-y,-z, x,-y,-z, x,-y,z, -x,-y,z,
        x,-y,z, x,-y,-z, x,y,-z, x,y,z,
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
    meshes = {
        tripodLeg:      createCylinder(0.025, 1.1, 16),
        tripodHead:     createCylinder(0.12, 0.08, 32),
        raBody:         createCylinder(0.09, 0.28, 32),
        raMotorBump:    createBox(0.12, 0.15, 0.10),
        decBody:        createCylinder(0.075, 0.25, 32),
        saddlePlate:    createBox(0.08, 0.25, 0.02),
        tubeBody:       createCylinder(0.065, 0.70, 32),
        dewShield:      createCylinder(0.075, 0.18, 32),
        focuserTube:    createCylinder(0.025, 0.10, 16),
        cwBar:          createCylinder(0.012, 0.50, 16),
        cwWeight:       createCylinder(0.07, 0.06, 32),
        ground:         createCylinder(3.0, 0.003, 48),
    };
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
function mat4Translate(x,y,z) { const m=mat4Identity(); m[12]=x; m[13]=y; m[14]=z; return m; }
function mat4RotateX(a) { const m=mat4Identity(), c=Math.cos(a), s=Math.sin(a); m[5]=c; m[6]=s; m[9]=-s; m[10]=c; return m; }
function mat4RotateY(a) { const m=mat4Identity(), c=Math.cos(a), s=Math.sin(a); m[0]=c; m[2]=-s; m[8]=s; m[10]=c; return m; }
function mat4RotateZ(a) { const m=mat4Identity(), c=Math.cos(a), s=Math.sin(a); m[0]=c; m[1]=s; m[4]=-s; m[5]=c; return m; }
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
    m[15]=1; return m;
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
        camDist = Math.max(2.5, Math.min(12, camDist));
    }, {passive:false});
}

// ─── render ──────────────────────────────────────────────────────────
const C = {
    tripod:     [0.85, 0.85, 0.88], 
    tripodHead: [0.15, 0.15, 0.15], 
    raBody:     [0.95, 0.95, 0.98], 
    motor:      [0.20, 0.20, 0.22], 
    decBody:    [0.95, 0.95, 0.98], 
    saddle:     [0.85, 0.15, 0.15], 
    tube:       [0.10, 0.10, 0.12], 
    dewShield:  [0.05, 0.05, 0.05], 
    focuser:    [0.60, 0.60, 0.60], 
    cwBar:      [0.90, 0.90, 0.90], 
    cwWeight:   [0.95, 0.95, 0.98], 
    ground:     [0.08, 0.10, 0.08], 
};

function renderLoop() {
    requestAnimationFrame(renderLoop);
    resize();
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

    // Update Sidereal Time
    let now = performance.now();
    let dt = (now - lastTimestamp) / 1000.0;
    lastTimestamp = now;
    LST = (LST + dt * SIDEREAL_RATE) % 360;

    // Track mode locks HA to maintain target RA
    if (isTracking && animMode === 'none' && !slewTimer) {
        currentHA = (LST - animRA_end + 360) % 360;
    }

    const eyeX = camDist * Math.cos(camPhi) * Math.sin(camTheta);
    const eyeY = camDist * Math.sin(camPhi) + 1.2;
    const eyeZ = camDist * Math.cos(camPhi) * Math.cos(camTheta);
    const view = mat4LookAt([eyeX, eyeY, eyeZ], [0, 1.1, 0], [0, 1, 0]);
    const proj = mat4Perspective(deg2rad(45), canvas.width/canvas.height, 0.1, 100);
    gl.uniformMatrix4fv(uView, false, view);
    gl.uniformMatrix4fv(uProj, false, proj);

    const latRad = deg2rad(LATITUDE);

    // Ground
    drawMesh(meshes.ground, mat4Identity(), C.ground);

    // Tripod Assembly
    const headY = 0.95;
    const legHalf = 0.55;
    const splay = deg2rad(22);
    for (let i = 0; i < 3; i++) {
        const a = deg2rad(i * 120);
        let m = mat4Translate(0, -legHalf, 0);
        m = mat4Multiply(mat4RotateY(-a), m);
        m = mat4Multiply(mat4RotateX(-splay), m);
        m = mat4Multiply(mat4RotateY(a), m);
        m = mat4Multiply(mat4Translate(0, headY, 0), m);
        drawMesh(meshes.tripodLeg, m, C.tripod);
    }
    drawMesh(meshes.tripodHead, mat4Translate(0, headY, 0), C.tripodHead);

    // Base Frame (Tilt to Latitude, Local Y points to NCP)
    let polarBase = mat4Multiply(
        mat4Translate(0, headY + 0.04, 0),
        mat4RotateX(latRad - Math.PI / 2)
    );

    // RA Housing
    let raHousingM = mat4Multiply(polarBase, mat4Translate(0, 0.14, 0));
    drawMesh(meshes.raBody, raHousingM, C.raBody);

    // RA Rotation (Driven by Mechanical HA)
    // Rotate Y axis. Minus sign ensures standard East-West convention.
    let polarRA = mat4Multiply(polarBase, mat4RotateY(deg2rad(-currentHA)));

    // DEC Hub
    let decHubPos = mat4Multiply(polarRA, mat4Translate(0, 0.30, 0));

    // DEC Housing
    // FIX: OTA is on Top (+Z), CW is on Bottom (-Z)
    const otaSide = 0.15;   
    const cwSide = -0.13;   
    const decCenterZ = (cwSide + otaSide) / 2;
    
    let decBodyCenter = mat4Multiply(decHubPos, mat4Translate(0, 0, decCenterZ));
    decBodyCenter = mat4Multiply(decBodyCenter, mat4RotateX(Math.PI / 2)); 
    drawMesh(meshes.decBody, decBodyCenter, C.decBody);
    
    // Motor housing detail
    drawMesh(meshes.raMotorBump, mat4Multiply(decHubPos, mat4Translate(0.08, 0, 0)), C.motor);

    // DEC Rotation (Rotates around local Z axis)
    // -90 ensures that at DEC=90 (Home), the tube is aligned with the RA axis (+Y).
    let decRot = mat4Multiply(decHubPos, mat4RotateZ(deg2rad(currentDEC - 90)));

    // ─── OTA Side (+Z Axis) ───
    let decOtaBase = mat4Multiply(decRot, mat4Translate(0, 0, otaSide));

    let saddleM = mat4Multiply(decOtaBase, mat4Translate(0, 0, 0.01)); // slight offset
    drawMesh(meshes.saddlePlate, saddleM, C.saddle);

    const tubeZOffset = 0.05 + 0.065; 
    let tubeBase = mat4Multiply(decOtaBase, mat4Translate(0, 0.15, tubeZOffset)); 
    drawMesh(meshes.tubeBody, tubeBase, C.tube);

    let dewM = mat4Multiply(tubeBase, mat4Translate(0, 0.42, 0));
    drawMesh(meshes.dewShield, dewM, C.dewShield);

    let focM = mat4Multiply(tubeBase, mat4Translate(0, -0.40, 0));
    drawMesh(meshes.focuserTube, focM, C.focuser);

    // ─── Counterweight Side (-Z Axis) ───
    let decCwBase = mat4Multiply(decRot, mat4Translate(0, 0, cwSide));

    let cwBarM = mat4Multiply(decCwBase, mat4Translate(0, 0, -0.25));
    cwBarM = mat4Multiply(cwBarM, mat4RotateX(Math.PI / 2)); 
    drawMesh(meshes.cwBar, cwBarM, C.cwBar);

    let w1M = mat4Multiply(decCwBase, mat4Translate(0, 0, -0.32));
    w1M = mat4Multiply(w1M, mat4RotateX(Math.PI / 2));
    drawMesh(meshes.cwWeight, w1M, C.cwWeight);

    let w2M = mat4Multiply(decCwBase, mat4Translate(0, 0, -0.40));
    w2M = mat4Multiply(w2M, mat4RotateX(Math.PI / 2));
    drawMesh(meshes.cwWeight, w2M, C.cwWeight);

    updatePositionDisplay();
}

// ─── position display ────────────────────────────────────────────────
function updatePositionDisplay() {
    let displayRA = (LST - currentHA + 360) % 360;
    let displayDEC = Math.max(-90, Math.min(90, currentDEC));

    document.getElementById('info-ra').textContent  = displayRA.toFixed(2);
    document.getElementById('info-dec').textContent = displayDEC.toFixed(2);
    document.getElementById('pos-ra-deg').textContent  = displayRA.toFixed(3) + '°';
    document.getElementById('pos-dec-deg').textContent = displayDEC.toFixed(3) + '°';
    document.getElementById('pos-ra-hms').textContent  = degToHMS(displayRA);
    document.getElementById('pos-dec-dms').textContent = degToDMS(displayDEC);
}

// ─── slewing (smooth animation) ──────────────────────────────────────
function animateTo(ra, dec) {
    isTracking = true;
    animMode = 'celestial';
    
    let currentRA = (LST - currentHA + 360) % 360;
    animRA_start = currentRA;
    animDEC_start = currentDEC;
    animRA_end = ((ra % 360) + 360) % 360;
    animDEC_end = Math.max(-90, Math.min(90, dec));

    let dRA = animRA_end - animRA_start;
    if (dRA > 180) dRA -= 360;
    if (dRA < -180) dRA += 360;
    animRA_end = animRA_start + dRA;

    const dist = Math.sqrt(dRA*dRA + (animDEC_end - animDEC_start)**2);
    const speed = parseFloat(document.getElementById('slew-speed').value) || 10;
    animDur = Math.max(300, (dist / speed) * 1000);
    animStart = performance.now();
    requestAnimationFrame(animStep);
}

// Explicit Park logic (Mechanical Zero)
function parkMount() {
    isTracking = false;
    animMode = 'mechanical';
    
    animHA_start = currentHA;
    animDEC_start = currentDEC;
    animHA_end = 0; // Mechanical Home
    animDEC_end = 90; // Mechanical Home
    
    let dHA = animHA_end - animHA_start;
    if (dHA > 180) dHA -= 360;
    if (dHA < -180) dHA += 360;
    animHA_end = animHA_start + dHA;
    
    const dist = Math.sqrt(dHA*dHA + (animDEC_end - animDEC_start)**2);
    const speed = parseFloat(document.getElementById('slew-speed').value) || 10;
    animDur = Math.max(300, (dist / speed) * 1000);
    animStart = performance.now();
    requestAnimationFrame(animStep);
}

function animStep(ts) {
    if (animMode === 'none') return;
    let t = (ts - animStart) / animDur;
    if (t >= 1) { t = 1; animMode = 'none'; }
    t = t < 0.5 ? 2*t*t : -1 + (4 - 2*t)*t; // ease-in-out
    
    if (animMode === 'celestial') {
        let r = animRA_start + (animRA_end - animRA_start) * t;
        currentDEC = animDEC_start + (animDEC_end - animDEC_start) * t;
        // Automatically translate interpolated RA into mechanical HA
        currentHA = (LST - r + 360) % 360;
    } else if (animMode === 'mechanical') {
        currentHA  = animHA_start + (animHA_end - animHA_start) * t;
        currentDEC = animDEC_start + (animDEC_end - animDEC_start) * t;
    }
    
    currentHA = ((currentHA % 360) + 360) % 360;
    if (animMode !== 'none') requestAnimationFrame(animStep);
}

function startSlew(axis, dir) {
    slewAxis = axis;
    slewDir  = dir;
    isTracking = false; // Stop tracking when manual control kicks in
    if (slewTimer) return;
    const step = () => {
        const speed = parseFloat(document.getElementById('slew-speed').value) || 10;
        const delta = speed * 0.03;  
        if (slewAxis === 'ra') {
            currentHA -= slewDir * delta; 
            currentHA = ((currentHA % 360) + 360) % 360;
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

function gotoCoordinate() {
    const raStr  = document.getElementById('input-ra').value;
    const decStr = document.getElementById('input-dec').value;
    const ra  = parseRA(raStr);
    const dec = parseDEC(decStr);
    if (ra === null) { alert('Invalid RA format. Use hh:mm:ss or degrees.'); return; }
    if (dec === null) { alert('Invalid DEC format. Use ±dd:mm:ss or degrees.'); return; }
    animateTo(ra, dec);
}

function gotoPreset(ra, dec) { animateTo(ra, dec); }
function updateSpeedLabel() { document.getElementById('speed-label').textContent = document.getElementById('slew-speed').value + '°/s'; }

document.addEventListener('DOMContentLoaded', initGL);