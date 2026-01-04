document.addEventListener('DOMContentLoaded', function() {
    const images = [
        {
            src: 'photo/SLT_SN2024ggi.png',
            caption: 'SLT g-, r-, and i-band images of SN2024ggi'
        },
        {
            src: 'photo/Kinder_dark_jpg.jpg',
            caption: 'Kinder Project Logo'
        },
        {
            src: 'photo/M42BG.jpg',
            caption: 'Orion Nebula (M42) and Horsehead Nebula (IC434) region'
        },
        {
            src: 'photo/M1_LOT.jpg',
            caption: 'Crab Nebula (M1) observed with LOT'
        },
        {
            src: 'photo/IC434_LOT.jpg',
            caption: 'Horsehead Nebula (IC434) observed with LOT'
        },
        {
            src: 'photo/M43_LOT.jpg',
            caption: 'Messier 43, neighbor to Messier 42, the Orion Nebula, observed with LOT'
        }
    ];

    let currentIndex = 0;
    const imgElement = document.querySelector('.banner-right img');
    const captionElement = document.querySelector('.banner-right p');
    
    // Preload images
    images.forEach(image => {
        const img = new Image();
        img.src = '/static/' + image.src;
    });

    function changeImage() {
        // Fade out
        imgElement.style.opacity = '0';
        
        setTimeout(() => {
            currentIndex = (currentIndex + 1) % images.length;
            
            // Update source and caption
            imgElement.src = '/static/' + images[currentIndex].src;
            // captionElement.textContent = images[currentIndex].caption; // User wants to fill this later, but if it's empty string it will clear it. 
            // If the user wants to hardcode one caption for all, I shouldn't touch it. 
            // But usually slideshows have different captions. 
            // The user said "The caption <p> leave it empty I will fill it". 
            // I will assume they will fill the array in JS later.
            if (images[currentIndex].caption) {
                captionElement.textContent = images[currentIndex].caption;
            } else {
                captionElement.textContent = ''; 
            }

            // Fade in
            imgElement.style.opacity = '1';
        }, 500); // Wait for fade out
    }

    // Change image every 6.5 seconds
    setInterval(changeImage, 6500);
    // Email obfuscation
    const emailElement = document.getElementById('obfuscated-email');
    if (emailElement) {
        const user = emailElement.getAttribute('data-user');
        const domain = emailElement.getAttribute('data-domain');
        emailElement.textContent = user + '@' + domain;
    }});
