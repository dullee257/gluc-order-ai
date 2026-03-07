import streamlit as st
st.file_uploader("Upload Image", key="img_uploader")
st.components.v1.html("""
<script>
    const parentDoc = window.parent.document;
    
    // Mutation observer to find the input file
    const observer = new MutationObserver((mutations) => {
        const fileInput = parentDoc.querySelector('input[type="file"]');
        if (fileInput && !fileInput.dataset.compressed) {
            fileInput.dataset.compressed = "true";
            
            // Backup the original setter
            const originalSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
            
            // Actually it's easier to intercept the change event? No, React listens to change event.
            // If we compress the file and create a new FileList, we can set it to the input and trigger React's change.
            
            fileInput.addEventListener('change', async function(e) {
                if (e.target.files.length === 0) return;
                const file = e.target.files[0];
                if (!file.type.startsWith('image/')) return;
                
                // If already compressed, let it pass
                if (file.name.includes('_compressed')) return;
                
                // Prevent Streamlit from handling this event immediately?
                e.stopImmediatePropagation();
                e.stopPropagation();
                e.preventDefault();
                
                console.log("Original file size:", file.size);
                
                // Compress logic
                const img = new Image();
                img.src = URL.createObjectURL(file);
                await new Promise(r => img.onload = r);
                
                const canvas = document.createElement('canvas');
                const ctx = canvas.getContext('2d');
                
                let scale = 1;
                if (file.size > 500 * 1024) {
                    scale = Math.sqrt((500 * 1024) / file.size);
                }
                
                canvas.width = img.width * scale;
                canvas.height = img.height * scale;
                ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
                
                canvas.toBlob((blob) => {
                    const compressedFile = new File([blob], file.name.replace(/\.[^/.]+$/, "") + "_compressed.jpg", {
                        type: 'image/jpeg',
                        lastModified: Date.now()
                    });
                    
                    console.log("Compressed size:", compressedFile.size);
                    
                    const dataTransfer = new DataTransfer();
                    dataTransfer.items.add(compressedFile);
                    fileInput.files = dataTransfer.files;
                    
                    // Trigger React change event
                    const event = new Event('change', { bubbles: true });
                    // To bypass React's event pooling/delegation overriding the value tracker:
                    const tracker = fileInput._valueTracker;
                    if (tracker) tracker.setValue(Date.now().toString());
                    
                    // Or standard react event dispatch:
                    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'files').set;
                    nativeInputValueSetter.call(fileInput, dataTransfer.files);
                    
                    fileInput.dispatchEvent(event);
                }, 'image/jpeg', 0.8);
            }, true); // useCapture to intercept before React
        }
    });
    
    observer.observe(parentDoc.body, { childList: true, subtree: true });
</script>
""")
