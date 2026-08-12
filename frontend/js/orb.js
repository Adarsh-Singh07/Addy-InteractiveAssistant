/**
 * Cinematic Orb UI
 * Uses Canvas 2D to render a high-fidelity, audio-reactive orb.
 */

const canvas = document.getElementById('orb-canvas');
const ctx = canvas.getContext('2d');
const width = canvas.width;
const height = canvas.height;
const centerX = width / 2;
const centerY = height / 2;

// Particles for the orb mesh
const particles = [];
const NUM_PARTICLES = 150;
const RADIUS = 120;

class Particle {
  constructor(angle, stack) {
    this.angle = angle;
    this.stack = stack;
    this.baseRadius = RADIUS * Math.sin(stack);
    this.baseZ = RADIUS * Math.cos(stack);
    
    // Add some noise offsets
    this.noiseOffsetX = Math.random() * 1000;
    this.noiseOffsetY = Math.random() * 1000;
    this.noiseSpeed = 0.005 + Math.random() * 0.01;
  }
}

// Generate spherical distribution
for (let i = 0; i < NUM_PARTICLES; i++) {
  const stack = Math.acos(2 * (i / NUM_PARTICLES) - 1);
  const angle = Math.sqrt(NUM_PARTICLES * Math.PI) * stack;
  particles.push(new Particle(angle, stack));
}

let time = 0;

function getAudioAmplitude() {
  let micAmp = 0;
  let speakerAmp = 0;

  // Read mic
  if (window.micAnalyser && window.isListening) {
    const dataArray = new Uint8Array(window.micAnalyser.frequencyBinCount);
    window.micAnalyser.getByteTimeDomainData(dataArray);
    let sum = 0;
    for (let i = 0; i < dataArray.length; i++) {
      const val = (dataArray[i] - 128) / 128.0;
      sum += val * val;
    }
    micAmp = Math.sqrt(sum / dataArray.length);
  }

  // Read speaker
  if (window.audioPlayer && window.audioPlayer._analyser) {
    const dataArray = new Uint8Array(window.audioPlayer._analyser.frequencyBinCount);
    window.audioPlayer._analyser.getByteTimeDomainData(dataArray);
    let sum = 0;
    for (let i = 0; i < dataArray.length; i++) {
      const val = (dataArray[i] - 128) / 128.0;
      sum += val * val;
    }
    speakerAmp = Math.sqrt(sum / dataArray.length);
  }

  return { micAmp, speakerAmp };
}

function drawOrb() {
  ctx.clearRect(0, 0, width, height);
  
  const { micAmp, speakerAmp } = getAudioAmplitude();
  
  // Base parameters on agentState
  const state = window.agentState || 'idle';
  let targetColor = 'rgba(0, 200, 255, 0.8)';
  let distortion = 0;
  let rotationSpeed = 0.002;
  
  // Theme color based on persona
  const isAtlas = document.body.classList.contains('persona-atlas');
  const isNova = document.body.classList.contains('persona-nova');
  
  let r = 0, g = 200, b = 255;
  if (isAtlas) { r = 255; g = 100; b = 100; }
  else if (isNova) { r = 150; g = 100; b = 255; }
  
  if (state === 'idle') {
    distortion = 5;
  } else if (state === 'listening') {
    distortion = 10 + (micAmp * 150);
    rotationSpeed = 0.005;
    g += 50; // brighten
  } else if (state === 'thinking') {
    distortion = 20 + Math.sin(time * 0.1) * 15;
    rotationSpeed = 0.01;
  } else if (state === 'speaking') {
    distortion = 15 + (speakerAmp * 200);
    rotationSpeed = 0.008 + (speakerAmp * 0.02);
    targetColor = `rgba(${r}, ${g}, ${b}, 1)`;
  }
  
  ctx.strokeStyle = `rgba(${r}, ${g}, ${b}, 0.5)`;
  ctx.fillStyle = `rgba(${r}, ${g}, ${b}, 0.8)`;
  ctx.lineWidth = 1.5;

  const projected = [];

  particles.forEach(p => {
    p.angle += rotationSpeed;
    
    // Simple pseudo-noise based on time
    const noise = Math.sin(time * p.noiseSpeed + p.noiseOffsetX) * Math.cos(time * p.noiseSpeed + p.noiseOffsetY);
    const rDist = p.baseRadius + (noise * distortion);
    
    const x = rDist * Math.cos(p.angle);
    const y = rDist * Math.sin(p.angle);
    
    // Simple 3D projection
    const z = p.baseZ;
    const scale = 200 / (200 + z);
    
    const px = centerX + x * scale;
    const py = centerY + y * scale;
    
    projected.push({ px, py, scale, z });
  });

  // Draw points
  projected.forEach(p => {
    ctx.beginPath();
    ctx.arc(p.px, p.py, Math.max(0.5, 2 * p.scale), 0, Math.PI * 2);
    ctx.fill();
  });
  
  // Draw connections for nearby points
  ctx.beginPath();
  for (let i = 0; i < projected.length; i++) {
    for (let j = i + 1; j < projected.length; j++) {
      const p1 = projected[i];
      const p2 = projected[j];
      const distSq = (p1.px - p2.px) ** 2 + (p1.py - p2.py) ** 2 + (p1.z - p2.z) ** 2;
      
      if (distSq < 1500) {
        ctx.moveTo(p1.px, p1.py);
        ctx.lineTo(p2.px, p2.py);
      }
    }
  }
  ctx.stroke();

  time++;
  requestAnimationFrame(drawOrb);
}

// Start animation loop
drawOrb();
