/**
 * Hommy Cottage - Client Interactive Script
 * Handles real-time price calculations, date validation, and UI interactions.
 */

document.addEventListener("DOMContentLoaded", function () {
    initDatePickers();
    initPriceCalculator();
    initGalleryThumbnails();
    initDestinationChips();
});

/**
 * Ensures check-in cannot be in the past and check-out is strictly after check-in.
 */
function initDatePickers() {
    const checkInInput = document.getElementById("check_in_date");
    const checkOutInput = document.getElementById("check_out_date");

    if (!checkInInput || !checkOutInput) return;

    const todayStr = new Date().toISOString().split("T")[0];
    if (!checkInInput.getAttribute("min")) {
        checkInInput.setAttribute("min", todayStr);
    }

    checkInInput.addEventListener("change", function () {
        if (!this.value) return;
        const checkInDate = new Date(this.value);
        const minCheckout = new Date(checkInDate);
        minCheckout.setDate(minCheckout.getDate() + 1);
        const minCheckOutStr = minCheckout.toISOString().split("T")[0];

        checkOutInput.setAttribute("min", minCheckOutStr);
        if (checkOutInput.value && checkOutInput.value <= this.value) {
            checkOutInput.value = minCheckOutStr;
        }
        calculateBookingPrice();
    });

    checkOutInput.addEventListener("change", function () {
        calculateBookingPrice();
    });
}

/**
 * Calculates and updates booking subtotal, 12% GST, and grand total in real-time.
 */
function initPriceCalculator() {
    calculateBookingPrice();
}

function calculateBookingPrice() {
    const checkInInput = document.getElementById("check_in_date");
    const checkOutInput = document.getElementById("check_out_date");
    const basePriceElem = document.getElementById("calc-base-price");

    if (!checkInInput || !checkOutInput || !basePriceElem) return;

    const basePrice = parseFloat(basePriceElem.dataset.price || 0);
    const gstRate = parseFloat(basePriceElem.dataset.taxRate || 0.12);

    const nightsElem = document.getElementById("calc-nights");
    const subtotalElem = document.getElementById("calc-subtotal");
    const taxElem = document.getElementById("calc-tax");
    const totalElem = document.getElementById("calc-total");
    const submitBtn = document.getElementById("btn-submit-booking");

    if (!checkInInput.value || !checkOutInput.value) {
        if (nightsElem) nightsElem.textContent = "1 night";
        if (subtotalElem) subtotalElem.textContent = formatINR(basePrice);
        if (taxElem) taxElem.textContent = formatINR(basePrice * gstRate);
        if (totalElem) totalElem.textContent = formatINR(basePrice + basePrice * gstRate);
        return;
    }

    const d1 = new Date(checkInInput.value);
    const d2 = new Date(checkOutInput.value);
    const timeDiff = d2.getTime() - d1.getTime();
    const nights = Math.ceil(timeDiff / (1000 * 3600 * 24));

    if (nights <= 0) {
        if (nightsElem) nightsElem.textContent = "Invalid dates";
        if (totalElem) totalElem.textContent = "₹0.00";
        if (submitBtn) submitBtn.disabled = true;
        return;
    }

    if (submitBtn) submitBtn.disabled = false;

    const subtotal = nights * basePrice;
    const tax = subtotal * gstRate;
    const total = subtotal + tax;

    if (nightsElem) nightsElem.textContent = `${nights} night${nights > 1 ? "s" : ""}`;
    if (subtotalElem) subtotalElem.textContent = formatINR(subtotal);
    if (taxElem) taxElem.textContent = formatINR(tax);
    if (totalElem) totalElem.textContent = formatINR(total);
}

function formatINR(val) {
    return "₹" + Number(val).toLocaleString("en-IN", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
}

/**
 * Swaps main image when a gallery thumbnail is clicked.
 */
function initGalleryThumbnails() {
    const thumbs = document.querySelectorAll(".gallery-thumb");
    const mainImg = document.getElementById("main-gallery-image");

    if (!thumbs.length || !mainImg) return;

    thumbs.forEach(thumb => {
        thumb.addEventListener("click", function () {
            mainImg.src = this.src;
            thumbs.forEach(t => t.classList.remove("border", "border-warning", "border-2"));
            this.classList.add("border", "border-warning", "border-2");
        });
    });
}

/**
 * Handles clicking on destination chips to fill the search box.
 */
function initDestinationChips() {
    const chips = document.querySelectorAll(".dest-chip");
    const cityInput = document.getElementById("search-city");

    if (!chips.length || !cityInput) return;

    chips.forEach(chip => {
        chip.addEventListener("click", function (e) {
            e.preventDefault();
            const targetCity = this.dataset.city;
            if (targetCity) {
                cityInput.value = targetCity;
                cityInput.closest("form").submit();
            }
        });
    });
}
