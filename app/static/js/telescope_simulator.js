// Telescope Simulator JavaScript
let aladin;
let isAladinReady = false;
let currentSurvey = 'CDS/P/DSS2/color';

const ICONS = {
    chevronDown: '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>',
    chevronRight: '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>'
};

// Initialize when page loads
document.addEventListener('DOMContentLoaded', function() {
    initializeAladin();
    calculateFOV();
    calculateMosaic();
});

// Initialize Aladin Lite
function initializeAladin() {
    const loadingElement = document.getElementById('aladinLoading');
    const aladinDiv = document.getElementById('aladin-lite-div');
    
    try {
        // Show loading state
        loadingElement.style.display = 'flex';
        aladinDiv.style.display = 'none';
        
        // Wait for Aladin to be ready, then initialize
        A.init.then(() => {
            aladin = A.aladin('#aladin-lite-div', {
                survey: currentSurvey,
                fov: 10,
                target: '20 51 05.74 +30 37 32.3',
                cooFrame: 'ICRS',
                showReticle: false,
                showZoomControl: false,
                showFullscreenControl: true,
                showLayersControl: false,
                showGotoControl: false,
                showShareControl: false,
                showCatalog: false,
                showFrame: false,
                showCooGrid: false,
                showProjectionControl: false,
                showSimbadPointerControl: false,
                showCooGridControl: false,
                showSettings: false,
                showLogo: true,
                showContextMenu: false,
                allowFullZoomout: true,
                realFullscreen: true,
                reticleColor: '#C5A059',
                reticleSize: 20,
                showStatusBar: false,
            });
            
            // Wait a moment for Aladin to fully load
            setTimeout(() => {
                loadingElement.style.display = 'none';
                aladinDiv.style.display = 'block';
                isAladinReady = true;
                
                // Set up Aladin monitors
                setupAladinMonitors();
                
                // Auto-display initial FOV after a longer delay
                setTimeout(() => {
                    console.log('Auto-displaying initial FOV...');
                    autoDisplayFOV();
                    adjustAladinFOV();
                }, 1500);
            }, 1000);
            
        }).catch(error => {
            console.error('Error initializing Aladin:', error);
            loadingElement.style.display = 'none';
            showNotification('Failed to load sky map', 'error');
        });
        
    } catch (error) {
        console.error('Error initializing Aladin:', error);
        loadingElement.style.display = 'none';
        showNotification('Failed to load sky map', 'error');
    }
}

// Change survey
function changeSurvey(surveyId) {
    // If called without parameter, get from select element (for backward compatibility)
    if (!surveyId) {
        const surveySelect = document.getElementById('surveySelect');
        if (surveySelect) {
            surveyId = surveySelect.value;
        }
    }
    
    if (!surveyId) {
        showNotification('No survey selected', 'error');
        return;
    }
    
    if (isAladinReady && aladin) {
        try {
            // Update active button
            document.querySelectorAll('.survey-btn').forEach(btn => {
                btn.classList.remove('active');
            });
            
            const activeButton = document.querySelector(`[data-survey="${surveyId}"]`);
            if (activeButton) {
                activeButton.classList.add('active');
            }
            
            // Change survey in Aladin
            aladin.setImageSurvey(surveyId);
            currentSurvey = surveyId;
        } catch (error) {
            console.error('Error changing survey:', error);
            showNotification('Failed to change survey', 'error');
        }
    } else {
        showNotification('Aladin not ready yet', 'error');
    }
}

// Toggle collapsible cards
function toggleCard(cardId) {
    const cardContent = document.getElementById(cardId);
    const icon = document.getElementById(cardId.replace('Card', 'Icon'));
    
    if (cardContent.classList.contains('collapsed')) {
        cardContent.classList.remove('collapsed');
        icon.classList.remove('collapsed');
        icon.innerHTML = ICONS.chevronDown;
    } else {
        cardContent.classList.add('collapsed');
        icon.classList.add('collapsed');
        icon.innerHTML = ICONS.chevronRight;
    }
}

// Toggle tile centers visibility
function toggleTileCenters() {
    const tileCentersContent = document.getElementById('tileCenters');
    const tileCentersIcon = document.getElementById('tileCentersIcon');
    
    if (tileCentersContent && tileCentersIcon) {
        tileCentersContent.classList.toggle('collapsed');
        tileCentersIcon.classList.toggle('collapsed');
        
        // Update icon
        if (tileCentersContent.classList.contains('collapsed')) {
            tileCentersIcon.innerHTML = ICONS.chevronRight;
        } else {
            tileCentersIcon.innerHTML = ICONS.chevronDown;
        }
    }
}

// Load telescope presets
function loadTelescopePreset() {
    const preset = document.getElementById('telescopePreset').value;
    
    const presets = {
        'Lulin LOT': { focal: 8000, aperture: 1000, reducer: 1.0 },
        'Lulin SLT': { focal: 3320, aperture: 400, reducer: 1.0 },
        'Lulin LATTE': { focal: 3454, aperture: 508, reducer: 1.0 },
    };
    
    if (preset && presets[preset]) {
        document.getElementById('focalLength').value = presets[preset].focal;
        document.getElementById('aperture').value = presets[preset].aperture;
        document.getElementById('focalReducer').value = presets[preset].reducer;
        calculateFOV();
    }
}

// Load camera presets
function loadCameraPreset() {
    const preset = document.getElementById('cameraPreset').value;
    
    const presets = {
        'LOT Sophia': { width: 30.72, height: 30.72, resX: 2048, resY: 2048 },
        'LOT SBIG ST-9XEI': { width: 10.2, height: 10.2, resX: 512, resY: 512 },
        'SLT Andor iKon-M 934': { width: 13.3, height: 13.3, resX: 1024, resY: 1024 },
        'Moravian C5-100M': { width: 44.0, height: 33.0, resX: 11664, resY: 8750 },
        'PlayerOne ZEUS(IMX455)': { width: 36.0, height: 24.0, resX: 9576, resY: 6388 },
        'PlayerOne Poseidon(IMX571)': { width: 23.5, height: 15.7, resX: 6252, resY: 4176 },
        'PlayerOne Artemis(IMX492)': { width: 19.2, height: 13.0, resX: 8288, resY: 5648 },
        'PlayerOne Ares(IMX533)': { width: 11.31, height: 11.31, resX: 3008, resY: 3008 },
        'PlayerOne Uranus(IMX585)': { width: 11.2, height: 6.3, resX: 3856, resY: 2180 },
    };
    
    if (preset && presets[preset]) {
        document.getElementById('sensorWidth').value = presets[preset].width;
        document.getElementById('sensorHeight').value = presets[preset].height;
        document.getElementById('resolutionX').value = presets[preset].resX;
        document.getElementById('resolutionY').value = presets[preset].resY;
        calculateFOV();
    }
}

// Calculate FOV and pixel scale
function calculateFOV() {
    const focalLength = parseFloat(document.getElementById('focalLength').value) || 530;
    const aperture = parseFloat(document.getElementById('aperture').value) || 106;
    const reducer = parseFloat(document.getElementById('focalReducer').value) || 1.0;
    const sensorWidth = parseFloat(document.getElementById('sensorWidth').value) || 23.6;
    const sensorHeight = parseFloat(document.getElementById('sensorHeight').value) || 15.6;
    const resX = parseInt(document.getElementById('resolutionX').value) || 6224;
    const resY = parseInt(document.getElementById('resolutionY').value) || 4168;
    
    const effectiveFocalLength = focalLength * reducer;
    const fRatio = effectiveFocalLength / aperture;
    const pixelSizeX = (sensorWidth / resX) * 1000; // in microns
    const pixelSizeY = (sensorHeight / resY) * 1000;
    const pixelScale = (pixelSizeX / effectiveFocalLength) * 206.265; // arcsec/pixel
    
    const fovWidthDeg = (sensorWidth / effectiveFocalLength) * 57.2958;
    const fovHeightDeg = (sensorHeight / effectiveFocalLength) * 57.2958;
    
    // Update displays
    document.getElementById('effectiveFocalLength').textContent = `${effectiveFocalLength.toFixed(0)}mm`;
    document.getElementById('fRatio').textContent = `f/${fRatio.toFixed(1)}`;
    document.getElementById('pixelScale').textContent = `${pixelScale.toFixed(2)} arcsec/pixel`;
    document.getElementById('singleFrameFOV').textContent = `${fovWidthDeg.toFixed(2)}° × ${fovHeightDeg.toFixed(2)}°`;
    
    // Update mosaic info without re-displaying FOV (avoid double clearing)
    updateMosaicInfo();
    
    // Clear old FOV and update with new parameters
    clearMosaicFromMap();
    setTimeout(() => {
        autoDisplayFOV();
        adjustAladinFOV();
    }, 300);
}

// Calculate mosaic information
function calculateMosaic() {
    const tilesX = parseInt(document.getElementById('mosaicX').value) || 1;
    const tilesY = parseInt(document.getElementById('mosaicY').value) || 1;
    const overlap = parseFloat(document.getElementById('overlap').value) || 10;
    const rotation = parseFloat(document.getElementById('rotation').value) || 0;
    
    const sensorWidth = parseFloat(document.getElementById('sensorWidth').value) || 23.6;
    const sensorHeight = parseFloat(document.getElementById('sensorHeight').value) || 15.6;
    const focalLength = parseFloat(document.getElementById('focalLength').value) || 530;
    const reducer = parseFloat(document.getElementById('focalReducer').value) || 1.0;
    const effectiveFocalLength = focalLength * reducer;
    
    const singleFrameFOVWidth = (sensorWidth / effectiveFocalLength) * 57.2958;
    const singleFrameFOVHeight = (sensorHeight / effectiveFocalLength) * 57.2958;
    
    const overlapFactor = (100 - overlap) / 100;
    const totalFOVWidth = singleFrameFOVWidth * (tilesX - 1) * overlapFactor + singleFrameFOVWidth;
    const totalFOVHeight = singleFrameFOVHeight * (tilesY - 1) * overlapFactor + singleFrameFOVHeight;
    
    const totalFrames = tilesX * tilesY;
    
    // Update Total FOV display
    const totalFOVElement = document.getElementById('totalFOV');
    if (totalFOVElement) {
        totalFOVElement.textContent = `${totalFOVWidth.toFixed(2)}°×${totalFOVHeight.toFixed(2)}°`;
    }
    
    // Update Tile Centers display
    updateTileCentersOnly();
    
    // Automatically update FOV display when mosaic parameters change
    clearMosaicFromMap();
    setTimeout(() => {
        autoDisplayFOV();
    }, 100);
}

// Update mosaic information display only (without redrawing FOV)
function updateMosaicInfo() {
    const tilesX = parseInt(document.getElementById('mosaicX').value) || 1;
    const tilesY = parseInt(document.getElementById('mosaicY').value) || 1;
    const overlap = parseFloat(document.getElementById('overlap').value) || 10;
    const rotation = parseFloat(document.getElementById('rotation').value) || 0;
    
    const sensorWidth = parseFloat(document.getElementById('sensorWidth').value) || 23.6;
    const sensorHeight = parseFloat(document.getElementById('sensorHeight').value) || 15.6;
    const focalLength = parseFloat(document.getElementById('focalLength').value) || 530;
    const reducer = parseFloat(document.getElementById('focalReducer').value) || 1.0;
    const effectiveFocalLength = focalLength * reducer;
    
    const singleFrameFOVWidth = (sensorWidth / effectiveFocalLength) * 57.2958;
    const singleFrameFOVHeight = (sensorHeight / effectiveFocalLength) * 57.2958;
    
    const overlapFactor = (100 - overlap) / 100;
    const totalFOVWidth = singleFrameFOVWidth * (tilesX - 1) * overlapFactor + singleFrameFOVWidth;
    const totalFOVHeight = singleFrameFOVHeight * (tilesY - 1) * overlapFactor + singleFrameFOVHeight;
    
    // Update Total FOV display
    const totalFOVElement = document.getElementById('totalFOV');
    if (totalFOVElement) {
        totalFOVElement.textContent = `${totalFOVWidth.toFixed(2)}°×${totalFOVHeight.toFixed(2)}°`;
    }
}

// Show mosaic on map as fixed overlay
function showMosaicOnMap() {
    if (!isAladinReady || !aladin) {
        console.log('Aladin not ready');
        return;
    }
    
    try {
        // Clear existing overlays
        clearMosaicFromMap();
        
        // Calculate mosaic grid parameters
        const tilesX = parseInt(document.getElementById('mosaicX').value) || 1;
        const tilesY = parseInt(document.getElementById('mosaicY').value) || 1;
        const overlap = parseFloat(document.getElementById('overlap').value) || 10;
        const rotation = parseFloat(document.getElementById('rotation').value) || 0;
        
        const sensorWidth = parseFloat(document.getElementById('sensorWidth').value) || 23.6;
        const sensorHeight = parseFloat(document.getElementById('sensorHeight').value) || 15.6;
        const focalLength = parseFloat(document.getElementById('focalLength').value) || 530;
        const reducer = parseFloat(document.getElementById('focalReducer').value) || 1.0;
        const effectiveFocalLength = focalLength * reducer;
        
        // Calculate FOV in degrees
        const singleFrameFOVWidth = (sensorWidth / effectiveFocalLength) * 57.2958;
        const singleFrameFOVHeight = (sensorHeight / effectiveFocalLength) * 57.2958;
        
        // Create fixed overlay on Aladin container
        createFixedFOVOverlay(tilesX, tilesY, singleFrameFOVWidth, singleFrameFOVHeight, overlap, rotation);
        
    } catch (error) {
        console.error('Error showing mosaic:', error);
        showNotification('Failed to show mosaic FOV', 'error');
    }
}

// Clear FOV displays
function clearMosaicFromMap() {
    try {
        console.log('Clearing all FOV displays...');
        
        // Remove fixed overlay
        if (window.currentFOVOverlay) {
            window.currentFOVOverlay.remove();
            window.currentFOVOverlay = null;
            console.log('Removed fixed FOV overlay');
        }
        
        // Also remove by ID if reference is lost
        const existingOverlay = document.getElementById('fovOverlay');
        if (existingOverlay) {
            existingOverlay.remove();
            console.log('Removed FOV overlay by ID');
        }
        
        console.log('FOV display clearing completed');
        
    } catch (error) {
        console.error('Error clearing FOV:', error);
    }
}

// Search by target name
function searchByName() {
    const targetName = document.getElementById('targetName').value.trim();
    if (!targetName) {
        showNotification('Please enter a target name', 'warning');
        return;
    }
    
    if (!isAladinReady || !aladin) {
        showNotification('Sky map not ready', 'warning');
        return;
    }
    
    try {
        // Use Aladin's built-in name resolver
        aladin.gotoObject(targetName);
        
        // Clear and auto-update FOV after moving
        setTimeout(() => {
            clearMosaicFromMap();
            setTimeout(() => {
                autoDisplayFOV();
                adjustAladinFOV();
            }, 100);
        }, 1000);
    } catch (error) {
        console.error('Error searching target:', error);
        showNotification('Target not found', 'error');
    }
}

// Go to coordinates
function gotoCoordinates() {
    const ra = parseFloat(document.getElementById('targetRA').value);
    const dec = parseFloat(document.getElementById('targetDEC').value);
    
    if (isNaN(ra) || isNaN(dec)) {
        showNotification('Please enter valid coordinates', 'warning');
        return;
    }
    
    if (!isAladinReady || !aladin) {
        showNotification('Sky map not ready', 'warning');
        return;
    }
    
    try {
        aladin.gotoRaDec(ra, dec);
        
        // Clear and auto-update FOV after moving
        setTimeout(() => {
            clearMosaicFromMap();
            setTimeout(() => {
                autoDisplayFOV();
                adjustAladinFOV();
            }, 100);
        }, 1000);
    } catch (error) {
        console.error('Error going to coordinates:', error);
        showNotification('Failed to go to coordinates', 'error');
    }
}

// Go to specific objects
function gotoObject(objectName) {
    const objects = {
        'm31': { ra: 10.6847, dec: 41.2691, name: 'M31 (Andromeda Galaxy)' },
        'm42': { ra: 83.8221, dec: -5.3911, name: 'M42 (Orion Nebula)' },
        'm57': { ra: 283.3962, dec: 33.0297, name: 'M57 (Ring Nebula)' },
        'm104': { ra: 189.9979, dec: -11.6233, name: 'M104 (Sombrero Galaxy)' },
        'ngc1068': { ra: 40.6696, dec: -0.0133, name: 'NGC 1068' },
        'veil': { ra: 312.9583, dec: 30.9167, name: 'Veil Nebula (NGC 6960)' }
    };
    
    if (!isAladinReady || !aladin) {
        showNotification('Sky map not ready', 'warning');
        return;
    }
    
    const obj = objects[objectName];
    if (obj) {
        try {
            aladin.gotoRaDec(obj.ra, obj.dec);
            
            // Clear and auto-update FOV after moving
            setTimeout(() => {
                clearMosaicFromMap();
                setTimeout(() => {
                    autoDisplayFOV();
                    adjustAladinFOV();
                }, 100);
            }, 1000);
        } catch (error) {
            console.error('Error going to object:', error);
            showNotification('Failed to go to object', 'error');
        }
    }
}

// Show notification
function showNotification(message, type = 'success') {
    const container = document.getElementById('notificationContainer');
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.textContent = message;
    
    container.appendChild(notification);
    
    // Auto remove after 3 seconds
    setTimeout(() => {
        notification.style.animation = 'slideOut 0.3s ease forwards';
        setTimeout(() => {
            if (container.contains(notification)) {
                container.removeChild(notification);
            }
        }, 300);
    }, 3000);
}

// Show single frame FOV as fixed overlay
function showSingleFrameFOV() {
    if (!isAladinReady || !aladin) {
        console.log('Aladin not ready');
        return;
    }
    
    try {
        // Clear existing overlays first
        clearMosaicFromMap();
        
        // Get camera and telescope parameters
        const sensorWidth = parseFloat(document.getElementById('sensorWidth').value) || 23.6;
        const sensorHeight = parseFloat(document.getElementById('sensorHeight').value) || 15.6;
        const focalLength = parseFloat(document.getElementById('focalLength').value) || 530;
        const reducer = parseFloat(document.getElementById('focalReducer').value) || 1.0;
        const rotation = parseFloat(document.getElementById('rotation').value) || 0;
        const effectiveFocalLength = focalLength * reducer;
        
        // Calculate FOV in degrees
        const fovWidth = (sensorWidth / effectiveFocalLength) * 57.2958;
        const fovHeight = (sensorHeight / effectiveFocalLength) * 57.2958;
        
        // Create fixed overlay for single frame
        createFixedFOVOverlay(1, 1, fovWidth, fovHeight, 0, rotation);
        
    } catch (error) {
        console.error('Error showing single frame FOV:', error);
        showNotification('Failed to show single frame FOV', 'error');
    }
}

// Adjust Aladin FOV to fit camera/mosaic FOV
function adjustAladinFOV() {
    if (!isAladinReady || !aladin) {
        console.log('Aladin not ready for FOV adjustment');
        return;
    }
    
    try {
        const tilesX = parseInt(document.getElementById('mosaicX').value) || 1;
        const tilesY = parseInt(document.getElementById('mosaicY').value) || 1;
        const overlap = parseFloat(document.getElementById('overlap').value) || 10;
        
        const sensorWidth = parseFloat(document.getElementById('sensorWidth').value) || 23.6;
        const sensorHeight = parseFloat(document.getElementById('sensorHeight').value) || 15.6;
        const focalLength = parseFloat(document.getElementById('focalLength').value) || 530;
        const reducer = parseFloat(document.getElementById('focalReducer').value) || 1.0;
        const effectiveFocalLength = focalLength * reducer;
        
        const singleFrameFOVWidth = (sensorWidth / effectiveFocalLength) * 57.2958;
        const singleFrameFOVHeight = (sensorHeight / effectiveFocalLength) * 57.2958;
        
        let targetFOV;
        
        if (tilesX === 1 && tilesY === 1) {
            // Single frame - use larger of width/height with some padding
            targetFOV = Math.max(singleFrameFOVWidth, singleFrameFOVHeight) * 2.5;
        } else {
            // Mosaic - calculate total FOV
            const overlapFactor = (100 - overlap) / 100;
            const totalFOVWidth = singleFrameFOVWidth * (tilesX - 1) * overlapFactor + singleFrameFOVWidth;
            const totalFOVHeight = singleFrameFOVHeight * (tilesY - 1) * overlapFactor + singleFrameFOVHeight;
            
            // Use larger dimension with padding
            targetFOV = Math.max(totalFOVWidth, totalFOVHeight) * 1.5;
        }
        
        // Clamp FOV to reasonable limits
        targetFOV = Math.max(0.1, Math.min(180, targetFOV));
        
        // Set Aladin FOV
        aladin.setFov(targetFOV);
        
        console.log(`Adjusted Aladin FOV to ${targetFOV.toFixed(2)}°`);
        
    } catch (error) {
        console.error('Error adjusting Aladin FOV:', error);
    }
}

// Auto-display FOV based on configuration
function autoDisplayFOV() {
    if (!isAladinReady || !aladin) {
        console.log('Aladin not ready for FOV display');
        return;
    }
    
    try {
        const tilesX = parseInt(document.getElementById('mosaicX').value) || 1;
        const tilesY = parseInt(document.getElementById('mosaicY').value) || 1;
        
        console.log(`Displaying FOV: ${tilesX}x${tilesY} tiles`);
        
        // Always display FOV automatically with a small delay
        setTimeout(() => {
            if (tilesX === 1 && tilesY === 1) {
                showSingleFrameFOV();
            } else {
                showMosaicOnMap();
            }
        }, 300);
    } catch (error) {
        console.error('Error auto-displaying FOV:', error);
    }
}

// Auto-update FOV when parameters change (legacy function, now calls autoDisplayFOV)
function autoUpdateFOV() {
    autoDisplayFOV();
}

// Create fixed FOV overlay on top of Aladin (not part of map coordinate system)
function createFixedFOVOverlay(tilesX, tilesY, fovWidth, fovHeight, overlap, rotation) {
    try {
        // Remove existing overlay if any
        const existingOverlay = document.getElementById('fovOverlay');
        if (existingOverlay) {
            existingOverlay.remove();
        }
        
        // Get Aladin container
        const aladinContainer = document.getElementById('aladin-lite-div');
        if (!aladinContainer) return;
        
        // Create overlay container
        const overlay = document.createElement('div');
        overlay.id = 'fovOverlay';
        overlay.style.position = 'absolute';
        overlay.style.top = '0';
        overlay.style.left = '0';
        overlay.style.width = '100%';
        overlay.style.height = '100%';
        overlay.style.pointerEvents = 'none';
        overlay.style.zIndex = '1000';
        
        // Get container dimensions
        const containerRect = aladinContainer.getBoundingClientRect();
        const centerX = containerRect.width / 2;
        const centerY = containerRect.height / 2;
        
        // Get current FOV of Aladin to calculate pixel scale
        const aladinFOV = aladin.getFov()[0]; // FOV in degrees
        const pixelsPerDegree = containerRect.width / aladinFOV;
        
        // Calculate frame dimensions in pixels
        const frameWidthPx = fovWidth * pixelsPerDegree;
        const frameHeightPx = fovHeight * pixelsPerDegree;
        
        // Calculate overlap
        const overlapFactor = (100 - overlap) / 100;
        const stepXPx = frameWidthPx * overlapFactor;
        const stepYPx = frameHeightPx * overlapFactor;
        
        // Create SVG for drawing
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.style.width = '100%';
        svg.style.height = '100%';
        svg.style.position = 'absolute';
        
        // Draw mosaic grid (always horizontal priority, rotation is visual only)
        let frameNumber = 1;
        for (let row = 0; row < tilesY; row++) {
            for (let col = 0; col < tilesX; col++) {
                const offsetX = (col - (tilesX - 1) / 2) * stepXPx;
                const offsetY = (row - (tilesY - 1) / 2) * stepYPx;
                
                let frameX = centerX + offsetX - frameWidthPx / 2;
                let frameY = centerY + offsetY - frameHeightPx / 2;
                
                // Apply rotation to the position (rotate around center)
                if (rotation !== 0) {
                    const rotRad = rotation * Math.PI / 180;
                    const cos = Math.cos(rotRad);
                    const sin = Math.sin(rotRad);
                    
                    // Rotate the offset position around center
                    const rotatedOffsetX = offsetX * cos - offsetY * sin;
                    const rotatedOffsetY = offsetX * sin + offsetY * cos;
                    
                    frameX = centerX + rotatedOffsetX - frameWidthPx / 2;
                    frameY = centerY + rotatedOffsetY - frameHeightPx / 2;
                }
                
                // Calculate overlap areas (in pixels)
                const overlapPx = frameWidthPx * (overlap / 100);
                const overlapPyPx = frameHeightPx * (overlap / 100);
                
                // Draw main frame (solid line)
                const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
                rect.setAttribute('x', frameX);
                rect.setAttribute('y', frameY);
                rect.setAttribute('width', frameWidthPx);
                rect.setAttribute('height', frameHeightPx);
                rect.setAttribute('fill', 'none');
                rect.setAttribute('stroke', '#C5A059');
                rect.setAttribute('stroke-width', '2');
                rect.setAttribute('stroke-opacity', '0.8');
                
                // Apply rotation to the rectangle itself (around its center)
                if (rotation !== 0) {
                    const frameCenterX = frameX + frameWidthPx / 2;
                    const frameCenterY = frameY + frameHeightPx / 2;
                    rect.setAttribute('transform', `rotate(${rotation} ${frameCenterX} ${frameCenterY})`);
                }
                
                svg.appendChild(rect);
                
                // Draw overlap areas with dashed lines (only if overlap > 0 and multiple tiles)
                if (overlap > 0 && (tilesX > 1 || tilesY > 1)) {
                    // Right overlap area (if not the rightmost column)
                    if (col < tilesX - 1) {
                        const overlapRect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
                        overlapRect.setAttribute('x', frameX + frameWidthPx - overlapPx);
                        overlapRect.setAttribute('y', frameY);
                        overlapRect.setAttribute('width', overlapPx);
                        overlapRect.setAttribute('height', frameHeightPx);
                        overlapRect.setAttribute('fill', 'none');
                        overlapRect.setAttribute('stroke', '#C5A059');
                        overlapRect.setAttribute('stroke-width', '1');
                        overlapRect.setAttribute('stroke-opacity', '0.5');
                        overlapRect.setAttribute('stroke-dasharray', '5,5');
                        
                        if (rotation !== 0) {
                            const frameCenterX = frameX + frameWidthPx / 2;
                            const frameCenterY = frameY + frameHeightPx / 2;
                            overlapRect.setAttribute('transform', `rotate(${rotation} ${frameCenterX} ${frameCenterY})`);
                        }
                        
                        svg.appendChild(overlapRect);
                    }
                    
                    // Bottom overlap area (if not the bottom row)
                    if (row < tilesY - 1) {
                        const overlapRect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
                        overlapRect.setAttribute('x', frameX);
                        overlapRect.setAttribute('y', frameY + frameHeightPx - overlapPyPx);
                        overlapRect.setAttribute('width', frameWidthPx);
                        overlapRect.setAttribute('height', overlapPyPx);
                        overlapRect.setAttribute('fill', 'none');
                        overlapRect.setAttribute('stroke', '#C5A059');
                        overlapRect.setAttribute('stroke-width', '1');
                        overlapRect.setAttribute('stroke-opacity', '0.5');
                        overlapRect.setAttribute('stroke-dasharray', '5,5');
                        
                        if (rotation !== 0) {
                            const frameCenterX = frameX + frameWidthPx / 2;
                            const frameCenterY = frameY + frameHeightPx / 2;
                            overlapRect.setAttribute('transform', `rotate(${rotation} ${frameCenterX} ${frameCenterY})`);
                        }
                        
                        svg.appendChild(overlapRect);
                    }
                }
                
                // Add frame label (numbered sequentially left-to-right, top-to-bottom)
                if (tilesX > 1 || tilesY > 1) {
                    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
                    text.setAttribute('x', frameX + frameWidthPx / 2);
                    text.setAttribute('y', frameY + frameHeightPx / 2);
                    text.setAttribute('fill', '#C5A059');
                    text.setAttribute('font-size', '12');
                    text.setAttribute('font-family', 'Arial');
                    text.setAttribute('text-anchor', 'middle');
                    text.setAttribute('dominant-baseline', 'middle');
                    text.textContent = frameNumber.toString();
                    
                    if (rotation !== 0) {
                        const frameCenterX = frameX + frameWidthPx / 2;
                        const frameCenterY = frameY + frameHeightPx / 2;
                        text.setAttribute('transform', `rotate(${rotation} ${frameCenterX} ${frameCenterY})`);
                    }
                    
                    svg.appendChild(text);
                }
                frameNumber++;
            }
        }
        
        // Add center crosshair
        const crosshairSize = 20;
        const hLine = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        hLine.setAttribute('x1', centerX - crosshairSize);
        hLine.setAttribute('y1', centerY);
        hLine.setAttribute('x2', centerX + crosshairSize);
        hLine.setAttribute('y2', centerY);
        hLine.setAttribute('stroke', '#C5A059');
        hLine.setAttribute('stroke-width', '1');
        hLine.setAttribute('stroke-opacity', '0.6');
        
        const vLine = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        vLine.setAttribute('x1', centerX);
        vLine.setAttribute('y1', centerY - crosshairSize);
        vLine.setAttribute('x2', centerX);
        vLine.setAttribute('y2', centerY + crosshairSize);
        vLine.setAttribute('stroke', '#C5A059');
        vLine.setAttribute('stroke-width', '1');
        vLine.setAttribute('stroke-opacity', '0.6');
        
        svg.appendChild(hLine);
        svg.appendChild(vLine);
        
        overlay.appendChild(svg);
        aladinContainer.appendChild(overlay);
        
        // Store reference for clearing
        window.currentFOVOverlay = overlay;
        
        console.log(`Created fixed FOV overlay: ${tilesX}x${tilesY} grid, ${fovWidth.toFixed(3)}° × ${fovHeight.toFixed(3)}° per frame`);
        
    } catch (error) {
        console.error('Error creating fixed FOV overlay:', error);
    }
}

// Update fixed FOV overlay when Aladin FOV changes
function updateFixedFOVOverlay() {
    if (window.currentFOVOverlay) {
        // Redraw the overlay with current parameters
        autoDisplayFOV();
    }
}

// Monitor Aladin FOV changes to update overlay
function setupAladinMonitors() {
    if (!isAladinReady || !aladin) return;
    
    try {
        // Monitor FOV changes (zoom events)
        aladin.on('zoomChanged', function() {
            setTimeout(updateFixedFOVOverlay, 100);
        });
        
        // Monitor view changes (pan events) - update tile centers when position changes
        aladin.on('positionChanged', function() {
            // Update tile centers coordinates when user pans the map
            setTimeout(updateTileCentersOnly, 100);
        });
        
        console.log('Aladin monitors set up');
    } catch (error) {
        console.log('Error setting up Aladin monitors:', error);
    }
}

// Coordinate conversion functions
function decimalToHMS(decimal) {
    // Convert decimal degrees to hours, minutes, seconds
    const hours = decimal / 15; // 1 hour = 15 degrees
    const h = Math.floor(Math.abs(hours));
    const m = Math.floor((Math.abs(hours) - h) * 60);
    const s = ((Math.abs(hours) - h) * 60 - m) * 60;
    
    return `${h.toString().padStart(2, '0')}h ${m.toString().padStart(2, '0')}m ${s.toFixed(1).padStart(4, '0')}s`;
}

function decimalToDMS(decimal) {
    // Convert decimal degrees to degrees, minutes, seconds
    const sign = decimal < 0 ? '-' : '+';
    const d = Math.floor(Math.abs(decimal));
    const m = Math.floor((Math.abs(decimal) - d) * 60);
    const s = ((Math.abs(decimal) - d) * 60 - m) * 60;
    
    return `${sign}${d.toString().padStart(2, '0')}° ${m.toString().padStart(2, '0')}' ${s.toFixed(1).padStart(4, '0')}"`;
}

// Update only tile centers coordinates without redrawing FOV
function updateTileCentersOnly() {
    if (!isAladinReady || !aladin) return;
    
    const tilesX = parseInt(document.getElementById('mosaicX').value) || 1;
    const tilesY = parseInt(document.getElementById('mosaicY').value) || 1;
    const overlap = parseFloat(document.getElementById('overlap').value) || 10;
    
    const sensorWidth = parseFloat(document.getElementById('sensorWidth').value) || 23.6;
    const sensorHeight = parseFloat(document.getElementById('sensorHeight').value) || 15.6;
    const focalLength = parseFloat(document.getElementById('focalLength').value) || 530;
    const reducer = parseFloat(document.getElementById('focalReducer').value) || 1.0;
    const effectiveFocalLength = focalLength * reducer;
    
    const singleFrameFOVWidth = (sensorWidth / effectiveFocalLength) * 57.2958;
    const singleFrameFOVHeight = (sensorHeight / effectiveFocalLength) * 57.2958;
    
    // Calculate and display tile centers
    let tileCoordinatesHTML = '';
    try {
        const centerRaDec = aladin.getRaDec();
        const centerRA = centerRaDec[0];
        const centerDec = centerRaDec[1];
        
        // Calculate offsets for each tile
        const overlapFactor = (100 - overlap) / 100;
        const stepX = singleFrameFOVWidth * overlapFactor;
        const stepY = singleFrameFOVHeight * overlapFactor;
        
        const startX = -(tilesX - 1) * stepX / 2;
        const startY = -(tilesY - 1) * stepY / 2;
        
        const tileItems = [];
        
        for (let row = 0; row < tilesY; row++) {
            for (let col = 0; col < tilesX; col++) {
                const offsetX = startX + col * stepX;
                const offsetY = startY + row * stepY;
                
                // Convert offsets to RA/Dec
                const tileRA = centerRA + offsetX / Math.cos(centerDec * Math.PI / 180);
                const tileDec = centerDec + offsetY;
                
                const tileNum = row * tilesX + col + 1;
                const raHMS = decimalToHMS(tileRA);
                const decDMS = decimalToDMS(tileDec);
                
                tileItems.push(`<div class="tile-center-item">T${tileNum}: RA ${raHMS}, Dec ${decDMS}</div>`);
            }
        }
        
        tileCoordinatesHTML = tileItems.join('');
    } catch (error) {
        console.error('Error getting current position:', error);
        const totalFrames = tilesX * tilesY;
        tileCoordinatesHTML = `<div class="tile-center-item">${totalFrames} tiles (${tilesX}×${tilesY})</div>`;
    }
    
    // Update Tile Centers display
    const tileCentersElement = document.getElementById('tileCenters');
    if (tileCentersElement) {
        tileCentersElement.innerHTML = tileCoordinatesHTML;
    }
}
