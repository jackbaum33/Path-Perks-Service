class CheckoutRack {
    constructor(options = {}) {
        // Default options
        this.options = {
            apiBaseUrl: options.apiBaseUrl || 'https://revshot-service.onrender.com/api',
            originalAmount: options.originalAmount || 0,
            cartUpdateCallback: options.cartUpdateCallback || null,
            successUrl: options.successUrl || window.location.href,
            cancelUrl: options.cancelUrl || window.location.href,
            elementId: options.elementId || 'checkout-rack-container',
            ...options
        };

        this.selectedProducts = [];
        this.products = [];
        this.totalAmount = this.options.originalAmount;

        // Initialize the component
        this.init();
    }

    async init() {
        // Create the container element
        this.container = document.getElementById(this.options.elementId);
        if (!this.container) {
            console.error(`Element with ID ${this.options.elementId} not found`);
            return;
        }

        // Add styles
        this.addStyles();

        // Load products
        await this.loadProducts();

        // Render the component
        this.render();
    }

    addStyles() {
        // Check if styles are already added
        if (document.getElementById('checkout-rack-styles')) return;

        const styleElement = document.createElement('style');
        styleElement.id = 'checkout-rack-styles';
        styleElement.textContent = document.querySelector('script[src$="checkout-rack.css"]').textContent;
        document.head.appendChild(styleElement);
    }

    async loadProducts() {
        try {
            const response = await fetch(`${this.options.apiBaseUrl}/products`);
            if (!response.ok) throw new Error('Failed to load products');
            
            this.products = await response.json();
        } catch (error) {
            console.error('Error loading products:', error);
            this.products = [];
        }
    }

    render() {
        this.container.innerHTML = `
            <div class="checkout-rack">
                <h2>You Might Also Like</h2>
                <div class="products-grid" id="products-grid">
                    ${this.products.map(product => this.renderProduct(product)).join('')}
                </div>
                <div class="total-price">
                    Total: $${(this.totalAmount / 100).toFixed(2)}
                </div>
                <button class="checkout-button" id="checkout-button">Proceed to Checkout</button>
            </div>
        `;

        // Add event listeners
        document.querySelectorAll('.product-card').forEach(card => {
            card.addEventListener('click', () => this.toggleProduct(card.dataset.productId));
        });

        document.getElementById('checkout-button').addEventListener('click', () => this.handleCheckout());
    }

    renderProduct(product) {
        const isSelected = this.selectedProducts.some(p => p.id === product.id);
        return `
            <div class="product-card ${isSelected ? 'selected' : ''}" data-product-id="${product.id}">
                <img src="${product.image_url}" alt="${product.name}" class="product-image">
                <div class="product-name">${product.name}</div>
                <div class="product-price">$${(product.price / 100).toFixed(2)}</div>
            </div>
        `;
    }

    toggleProduct(productId) {
        const product = this.products.find(p => p.id === productId);
        if (!product) return;

        const index = this.selectedProducts.findIndex(p => p.id === productId);
        
        if (index === -1) {
            // Add to selection
            this.selectedProducts.push(product);
            this.totalAmount += product.price;
        } else {
            // Remove from selection
            this.selectedProducts.splice(index, 1);
            this.totalAmount -= product.price;
        }

        // Update the display
        this.updateDisplay();

        // Notify the parent page if callback is provided
        if (this.options.cartUpdateCallback) {
            this.options.cartUpdateCallback(this.totalAmount);
        }
    }

    updateDisplay() {
        // Update selected state of product cards
        document.querySelectorAll('.product-card').forEach(card => {
            const isSelected = this.selectedProducts.some(p => p.id === card.dataset.productId);
            card.classList.toggle('selected', isSelected);
        });

        // Update total price display
        const totalElement = document.querySelector('.total-price');
        if (totalElement) {
            totalElement.textContent = `Total: $${(this.totalAmount / 100).toFixed(2)}`;
        }
    }

    async handleCheckout() {
        try {
            const response = await fetch(`${this.options.apiBaseUrl}/checkout`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    items: this.selectedProducts,
                    original_amount: this.options.originalAmount,
                    success_url: this.options.successUrl,
                    cancel_url: this.options.cancelUrl
                })
            });

            if (!response.ok) {
                throw new Error('Checkout failed');
            }

            const data = await response.json();
            window.location.href = data.url;
        } catch (error) {
            console.error('Error during checkout:', error);
            alert('There was an error processing your checkout. Please try again.');
        }
    }
}

// Export for use as a module
if (typeof module !== 'undefined' && module.exports) {
    module.exports = CheckoutRack;
} else {
    window.CheckoutRack = CheckoutRack;
}