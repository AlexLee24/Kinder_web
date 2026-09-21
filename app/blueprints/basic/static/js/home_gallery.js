// Home Gallery Integration - Full featured version with edit/delete/upload

class HomeGalleryManager {
    constructor() {
        this.galleryItems = [];
        this.currentIndex = 0;
        this.init();
    }

    async init() {
        this.cacheElements();
        await this.loadGalleryData();
        this.renderGallery();
        this.attachEventListeners();
    }

    cacheElements() {
        this.grid = document.getElementById('homeGalleryGrid');
        if (!this.grid) return false;

        // Lightbox elements
        this.lightbox = document.getElementById('homeLightbox');
        this.lightboxBackdrop = document.getElementById('homeLightboxBackdrop');
        this.lightboxImg = document.getElementById('homeLightboxImg');
        this.lightboxTitle = document.getElementById('homeLightboxTitle');
        this.lightboxCaption = document.getElementById('homeLightboxCaption');
        this.lightboxAuthor = document.getElementById('homeLightboxAuthor');
        this.lightboxClose = document.getElementById('homeLightboxClose');
        this.lightboxPrev = document.getElementById('homeLightboxPrev');
        this.lightboxNext = document.getElementById('homeLightboxNext');
        this.lightboxEdit = document.getElementById('homeLightboxEdit');
        this.lightboxDelete = document.getElementById('homeLightboxDelete');
        this.dockItems = document.getElementById('homeDockItems');

        // Edit modal elements
        this.editModal = document.getElementById('homeEditModal');
        this.editModalBackdrop = document.getElementById('homeEditModalBackdrop');
        this.editForm = document.getElementById('homeEditForm');
        this.editModalClose = document.getElementById('homeEditModalClose');
        this.editCancel = document.getElementById('homeEditCancel');
        this.editTitle = document.getElementById('homeEditTitle');
        this.editDescription = document.getElementById('homeEditDescription');
        this.editPhotographer = document.getElementById('homeEditPhotographer');
        this.editSpan = document.getElementById('homeEditSpan');
        this.editSaveText = document.getElementById('homeEditSaveText');
        this.editSaveSpinner = document.getElementById('homeEditSaveSpinner');
        this.editError = document.getElementById('homeEditError');

        // Upload modal elements
        this.uploadBtn = document.getElementById('homeUploadBtn');
        this.uploadModal = document.getElementById('homeUploadModal');
        this.uploadModalBackdrop = document.getElementById('homeUploadModalBackdrop');
        this.uploadForm = document.getElementById('homeUploadForm');
        this.uploadModalClose = document.getElementById('homeUploadModalClose');
        this.uploadCancel = document.getElementById('homeUploadCancel');
        this.uploadZone = document.getElementById('homeUploadZone');
        this.imageFile = document.getElementById('homeImageFile');
        this.imagePreview = document.getElementById('homeImagePreview');
        this.previewImg = document.getElementById('homePreviewImg');
        this.removePreview = document.getElementById('homeRemovePreview');
        this.submitBtn = document.getElementById('homeSubmitBtn');
        this.submitText = document.getElementById('homeSubmitText');
        this.submitSpinner = document.getElementById('homeSubmitSpinner');
        this.successMessage = document.getElementById('homeSuccessMessage');
        this.errorMessage = document.getElementById('homeErrorMessage');
        this.errorText = document.getElementById('homeErrorText');

        return true;
    }

    async loadGalleryData() {
        try {
            const response = await fetch('/api/gallery');
            if (!response.ok) {
                throw new Error('Failed to load gallery');
            }
            const data = await response.json();
            this.galleryItems = data.items || [];
        } catch (error) {
            console.error('Failed to load gallery:', error);
            this.galleryItems = [];
        }
    }

    renderGallery() {
        this.grid.innerHTML = '';

        if (this.galleryItems.length === 0) {
            this.grid.innerHTML = '<p style="grid-column: 1/-1; text-align: center; color: rgba(255,255,255,0.5); padding: 40px;">Gallery coming soon</p>';
            return;
        }

        // Show all images (not limited to 8)
        this.galleryItems.forEach((item, index) => {
            const galleryItem = this.createGalleryItem(item, index);
            this.grid.appendChild(galleryItem);
        });
    }

    createGalleryItem(item, index) {
        const div = document.createElement('div');
        // Apply span class if it exists (e.g., col-span-2 row-span-1)
        const spanClass = item.span || 'col-span-1 row-span-1';
        div.className = `home-gallery-item ${spanClass}`;
        div.innerHTML = `
            <img src="${item.thumbnail_url}" alt="${item.title}" loading="lazy" />
            <div class="home-gallery-overlay">
                <p class="home-gallery-title">${this.escapeHtml(item.title)}</p>
            </div>
        `;
        div.addEventListener('click', () => this.openLightbox(index));
        return div;
    }

    openLightbox(index) {
        this.currentIndex = index;
        const item = this.galleryItems[index];

        this.lightboxImg.src = item.image_url;
        this.lightboxTitle.textContent = item.title;
        this.lightboxCaption.textContent = item.description || '';
        this.lightboxAuthor.textContent = `By ${item.photographer || 'Anonymous'}`;

        // Store item ID for delete/edit
        if (this.lightboxDelete) {
            this.lightboxDelete.dataset.itemId = item.id;
        }
        if (this.lightboxEdit) {
            this.lightboxEdit.dataset.itemId = item.id;
        }

        this.renderDock();
        this.lightbox.hidden = false;
        document.body.style.overflow = 'hidden';
    }

    closeLightbox() {
        this.lightbox.hidden = true;
        document.body.style.overflow = 'auto';
    }

    renderDock() {
        this.dockItems.innerHTML = '';
        this.galleryItems.forEach((item, index) => {
            const dockItem = document.createElement('div');
            dockItem.className = `home-dock-item ${index === this.currentIndex ? 'active' : ''}`;
            dockItem.innerHTML = `<img src="${item.thumbnail_url}" alt="${item.title}" />`;
            dockItem.addEventListener('click', () => this.openLightbox(index));
            this.dockItems.appendChild(dockItem);
        });
    }

    showPrev() {
        this.currentIndex = (this.currentIndex - 1 + this.galleryItems.length) % this.galleryItems.length;
        this.openLightbox(this.currentIndex);
    }

    showNext() {
        this.currentIndex = (this.currentIndex + 1) % this.galleryItems.length;
        this.openLightbox(this.currentIndex);
    }

    // Edit functionality
    openEditModal() {
        const item = this.galleryItems[this.currentIndex];

        this.editTitle.value = item.title;
        this.editDescription.value = item.description || '';
        this.editPhotographer.value = item.photographer || '';
        this.editSpan.value = item.span || 'col-span-1 row-span-1';

        this.editForm.dataset.itemId = item.id;
        this.editError.style.display = 'none';

        this.editModal.hidden = false;
        document.body.style.overflow = 'hidden';
    }

    closeEditModal() {
        this.editModal.hidden = true;
        document.body.style.overflow = 'auto';
        this.editError.style.display = 'none';
    }

    async submitEditForm(e) {
        e.preventDefault();

        const itemId = this.editForm.dataset.itemId;
        const data = {
            title: this.editTitle.value.trim(),
            description: this.editDescription.value.trim(),
            photographer: this.editPhotographer.value.trim(),
            span: this.editSpan.value
        };

        if (!data.title) {
            this.showEditError('Title is required');
            return;
        }

        const saveBtn = this.editForm.querySelector('button[type="submit"]');
        saveBtn.disabled = true;
        this.editSaveText.style.display = 'none';
        this.editSaveSpinner.style.display = 'inline-flex';

        try {
            const response = await fetch(`/api/gallery/${itemId}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(data)
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.error || 'Failed to update image');
            }

            // Update local data
            const itemIndex = this.galleryItems.findIndex(item => item.id === itemId);
            if (itemIndex !== -1) {
                this.galleryItems[itemIndex] = {
                    ...this.galleryItems[itemIndex],
                    ...data
                };
            }

            this.closeEditModal();
            // Re-render gallery to apply span changes
            this.renderGallery();
            // Then open lightbox at the same index
            this.openLightbox(this.currentIndex);
            alert('Image updated successfully');
        } catch (error) {
            console.error('Update error:', error);
            this.showEditError(error.message || 'Failed to update image');
        } finally {
            saveBtn.disabled = false;
            this.editSaveText.style.display = 'inline';
            this.editSaveSpinner.style.display = 'none';
        }
    }

    showEditError(message) {
        this.editError.textContent = message;
        this.editError.style.display = 'block';
    }

    // Delete functionality
    async deleteItem() {
        const itemId = this.lightboxDelete.dataset.itemId;
        if (!confirm('Are you sure you want to delete this image?')) return;

        try {
            const response = await fetch(`/api/gallery/${itemId}`, {
                method: 'DELETE',
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) {
                throw new Error('Failed to delete image');
            }

            this.galleryItems = this.galleryItems.filter(item => item.id != itemId);
            this.closeLightbox();
            this.renderGallery();
            alert('Image deleted successfully');
        } catch (error) {
            console.error('Delete error:', error);
            alert('Failed to delete image');
        }
    }

    // Upload functionality
    openUploadModal() {
        if (this.uploadModal) {
            this.uploadModal.hidden = false;
            document.body.style.overflow = 'hidden';
            this.resetUploadForm();
        }
    }

    closeUploadModal() {
        if (this.uploadModal) {
            this.uploadModal.hidden = true;
            document.body.style.overflow = 'auto';
            this.resetUploadForm();
        }
    }

    resetUploadForm() {
        if (this.uploadForm) {
            this.uploadForm.reset();
            this.imagePreview.style.display = 'none';
            this.successMessage.style.display = 'none';
            this.errorMessage.style.display = 'none';
            this.uploadForm.style.display = 'flex';
        }
    }

    setupUploadHandlers() {
        if (!this.uploadZone) return;

        // Click to browse
        this.uploadZone.addEventListener('click', () => {
            this.imageFile.click();
        });

        // Drag and drop
        this.uploadZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            this.uploadZone.classList.add('dragover');
        });

        this.uploadZone.addEventListener('dragleave', () => {
            this.uploadZone.classList.remove('dragover');
        });

        this.uploadZone.addEventListener('drop', (e) => {
            e.preventDefault();
            this.uploadZone.classList.remove('dragover');
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                this.imageFile.files = files;
                this.handleFileSelect();
            }
        });

        // File input change
        this.imageFile.addEventListener('change', () => {
            this.handleFileSelect();
        });

        // Remove preview
        if (this.removePreview) {
            this.removePreview.addEventListener('click', () => {
                this.imageFile.value = '';
                this.imagePreview.style.display = 'none';
            });
        }

        // Form submit
        this.uploadForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            await this.submitUploadForm();
        });
    }

    handleFileSelect() {
        const file = this.imageFile.files[0];
        if (!file) return;

        // Validate file type
        if (!file.type.startsWith('image/')) {
            this.showUploadError('Please select an image file');
            return;
        }

        // Validate file size (10MB)
        if (file.size > 10 * 1024 * 1024) {
            this.showUploadError('File size must be less than 10MB');
            return;
        }

        // Show preview
        const reader = new FileReader();
        reader.onload = (e) => {
            this.previewImg.src = e.target.result;
            this.imagePreview.style.display = 'block';
        };
        reader.readAsDataURL(file);

        this.errorMessage.style.display = 'none';
    }

    async submitUploadForm() {
const file = this.imageFile.files[0];
        if (!file) {
            this.showUploadError('Please select an image file');
            return;
        }

        const title = document.getElementById('homeUploadTitle').value.trim();
        if (!title) {
            this.showUploadError('Please enter a title');
            return;
        }

        // Prepare form data
        const formData = new FormData();
        formData.append('image', file);
        formData.append('title', title);
        formData.append('description', document.getElementById('homeUploadDescription').value);
        formData.append('photographer', document.getElementById('homeUploadPhotographer').value);
        formData.append('span', document.getElementById('homeUploadSpan').value);

        // Show loading state
        this.setUploadLoading(true);

        try {
            const response = await fetch('/api/gallery/upload', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                const data = await response.json();
                throw new Error(data.error || 'Upload failed');
            }

            // Success
            this.uploadForm.style.display = 'none';
            this.successMessage.style.display = 'flex';
            
            // Reload gallery data
            await this.loadGalleryData();
            this.renderGallery();

            // Close modal after delay
            setTimeout(() => {
                this.closeUploadModal();
            }, 2000);
        } catch (error) {
            console.error('Upload error:', error);
            this.showUploadError(error.message || 'Failed to upload image');
        } finally {
            this.setUploadLoading(false);
        }
    }

    setUploadLoading(isLoading) {
        this.submitBtn.disabled = isLoading;
        if (isLoading) {
            this.submitText.style.display = 'none';
            this.submitSpinner.style.display = 'inline-flex';
        } else {
            this.submitText.style.display = 'inline';
            this.submitSpinner.style.display = 'none';
        }
    }

    showUploadError(message) {
        this.errorText.textContent = message;
        this.errorMessage.style.display = 'flex';
    }

    attachEventListeners() {
        // Lightbox
        this.lightboxClose.addEventListener('click', () => this.closeLightbox());
        this.lightboxBackdrop?.addEventListener('click', () => this.closeLightbox());
        this.lightboxPrev.addEventListener('click', () => this.showPrev());
        this.lightboxNext.addEventListener('click', () => this.showNext());

        // Edit
        if (this.lightboxEdit) {
            this.lightboxEdit.addEventListener('click', () => this.openEditModal());
        }

        if (this.editModal) {
            this.editModalClose.addEventListener('click', () => this.closeEditModal());
            this.editModalBackdrop?.addEventListener('click', () => this.closeEditModal());
            this.editCancel.addEventListener('click', () => this.closeEditModal());
            this.editForm.addEventListener('submit', (e) => this.submitEditForm(e));
        }

        // Delete
        if (this.lightboxDelete) {
            this.lightboxDelete.addEventListener('click', () => this.deleteItem());
        }

        // Upload
        if (this.uploadBtn) {
            this.uploadBtn.addEventListener('click', () => this.openUploadModal());
        }

        if (this.uploadModal) {
            this.uploadModalClose.addEventListener('click', () => this.closeUploadModal());
            this.uploadModalBackdrop?.addEventListener('click', () => this.closeUploadModal());
            this.uploadCancel.addEventListener('click', () => this.closeUploadModal());
            this.setupUploadHandlers();
        }

        // Keyboard navigation
        document.addEventListener('keydown', (e) => {
            if (this.editModal && !this.editModal.hidden) return;
            if (this.uploadModal && !this.uploadModal.hidden) return;
            if (this.lightbox.hidden) return;
            if (e.key === 'ArrowLeft') this.showPrev();
            if (e.key === 'ArrowRight') this.showNext();
            if (e.key === 'Escape') this.closeLightbox();
        });
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    new HomeGalleryManager();
});


