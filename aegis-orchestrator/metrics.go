package main

import (
	"encoding/json"
	"math"
	"math/bits"
	"net/http"
	"sync"
	"time"
)

// Simple BitWriter for bit-level Gorilla packing
type BitWriter struct {
	buf []byte
	b   byte
	bit uint
}

func (bw *BitWriter) WriteBit(bit byte) {
	if bit > 0 {
		bw.b |= (1 << (7 - bw.bit))
	}
	bw.bit++
	if bw.bit == 8 {
		bw.buf = append(bw.buf, bw.b)
		bw.b = 0
		bw.bit = 0
	}
}

func (bw *BitWriter) WriteBits(val uint64, n uint) {
	for i := uint(0); i < n; i++ {
		bit := byte((val >> (n - 1 - i)) & 1)
		bw.WriteBit(bit)
	}
}

func (bw *BitWriter) Flush() {
	if bw.bit > 0 {
		bw.buf = append(bw.buf, bw.b)
		bw.b = 0
		bw.bit = 0
	}
}

// Global TSDB stats
type TSDBStats struct {
	TotalPoints      int     `json:"total_points"`
	RawSizeBytes     int     `json:"raw_size_bytes"`
	GorillaSizeBytes int     `json:"gorilla_size_bytes"`
	CompressionRatio float64 `json:"compression_ratio"` // e.g. 11.5
	GorillaLog       string  `json:"gorilla_log"`
}

var (
	metricsMu   sync.Mutex
	storedTimes []int64
	storedCPUs  []float64
	storedRAMs  []float64
	tsdbStats   TSDBStats
)

func initMetricsTSDB() {
	// Generate mock historical resource metrics for the last 60 seconds
	now := time.Now().Unix()
	for i := 60; i > 0; i-- {
		storedTimes = append(storedTimes, now-int64(i))
		storedCPUs = append(storedCPUs, 15.0+math.Sin(float64(i)/5.0)*5.0)
		storedRAMs = append(storedRAMs, 64.2)
	}
	runGorillaCompression()
}

// Gorilla Compression algorithm for float64 value series
func compressValues(bw *BitWriter, vals []float64) {
	if len(vals) == 0 {
		return
	}
	// Write first value in full (64 bits)
	v0 := math.Float64bits(vals[0])
	bw.WriteBits(v0, 64)

	var prevLeading uint = 999
	var prevTrailing uint = 999
	prevV := vals[0]

	for i := 1; i < len(vals); i++ {
		v := vals[i]
		bitsV := math.Float64bits(v)
		bitsPrevV := math.Float64bits(prevV)
		xor := bitsV ^ bitsPrevV

		if xor == 0 {
			bw.WriteBit(0)
		} else {
			bw.WriteBit(1)
			leading := uint(bits.LeadingZeros64(xor))
			trailing := uint(bits.TrailingZeros64(xor))
			if leading > 31 {
				leading = 31
			}

			// If leading/trailing zeros fall inside previous bounds, store in compact form
			if prevLeading != 999 && leading >= prevLeading && trailing >= prevTrailing {
				bw.WriteBit(0)
				bitsToWrite := xor >> prevTrailing
				length := 64 - prevLeading - prevTrailing
				bw.WriteBits(bitsToWrite, length)
			} else {
				bw.WriteBit(1)
				bw.WriteBits(uint64(leading), 5)
				length := 64 - leading - trailing
				if length == 0 {
					length = 1
				}
				bw.WriteBits(uint64(length), 6)
				bitsToWrite := xor >> trailing
				bw.WriteBits(bitsToWrite, length)
				prevLeading = leading
				prevTrailing = trailing
			}
		}
		prevV = v
	}
}

// Gorilla Compression algorithm for timestamps (delta-of-deltas)
func compressTimestamps(bw *BitWriter, times []int64) {
	if len(times) == 0 {
		return
	}
	// Write t0 in full (64 bits)
	bw.WriteBits(uint64(times[0]), 64)
	if len(times) < 2 {
		return
	}

	// Write first delta in full (14 bits)
	firstDelta := times[1] - times[0]
	bw.WriteBits(uint64(firstDelta), 14)

	prevDelta := firstDelta
	for i := 2; i < len(times); i++ {
		delta := times[i] - times[i-1]
		dod := delta - prevDelta // Delta of delta

		if dod == 0 {
			bw.WriteBit(0)
		} else if dod >= -63 && dod <= 64 {
			bw.WriteBits(2, 2) // '10' bits
			bw.WriteBits(uint64(dod+63), 7)
		} else if dod >= -255 && dod <= 256 {
			bw.WriteBits(6, 3) // '110' bits
			bw.WriteBits(uint64(dod+255), 9)
		} else if dod >= -2047 && dod <= 2048 {
			bw.WriteBits(14, 4) // '1110' bits
			bw.WriteBits(uint64(dod+2047), 12)
		} else {
			bw.WriteBits(15, 4) // '1111' bits
			bw.WriteBits(uint64(dod), 32)
		}
		prevDelta = delta
	}
}

func runGorillaCompression() {
	metricsMu.Lock()
	defer metricsMu.Unlock()

	bw := &BitWriter{}
	compressTimestamps(bw, storedTimes)
	compressValues(bw, storedCPUs)
	bw.Flush()

	rawSize := len(storedTimes)*8 + len(storedCPUs)*8
	gorillaSize := len(bw.buf)
	ratio := float64(rawSize) / float64(gorillaSize)

	tsdbStats = TSDBStats{
		TotalPoints:      len(storedTimes),
		RawSizeBytes:     rawSize,
		GorillaSizeBytes: gorillaSize,
		CompressionRatio: ratio,
		GorillaLog:       "Gorilla: Сжатие временных меток через Delta-of-Deltas. Сжатие float64 через XOR + Leading/Trailing zero packing.",
	}
}

func handleMetrics(w http.ResponseWriter, r *http.Request) {
	runGorillaCompression()

	metricsMu.Lock()
	stats := tsdbStats
	metricsMu.Unlock()

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(stats)
}

func handleBilling(w http.ResponseWriter, r *http.Request) {
	state.mu.RLock()
	defer state.mu.RUnlock()

	response := map[string]interface{}{
		"balance":      state.Balance,
		"billing_rate": state.BillingRate,
		"transactions": state.Transactions,
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)
}

// Background billing ticker (decrement balance every second based on active containers)
func billingLoop() {
	ticker := time.NewTicker(1 * time.Second)
	aggCounter := 0
	aggAmount := 0.0

	for range ticker.C {
		state.mu.Lock()

		if state.BillingRate > 0 {
			cost := state.BillingRate
			state.Balance -= cost
			aggAmount += cost
			aggCounter++

			// Add transaction history entry every 10 seconds to keep clean
			if aggCounter >= 10 {
				tx := Transaction{
					Time:   time.Now().Format("15:04:05"),
					Amount: -aggAmount,
					Desc:   "Списание за аренду вычислительных ресурсов Aegis-Compute",
				}
				state.Transactions = append([]Transaction{tx}, state.Transactions...)
				if len(state.Transactions) > 15 {
					state.Transactions = state.Transactions[:15]
				}
				aggCounter = 0
				aggAmount = 0.0
				go saveState()
			}
		}

		// Push metrics point to Gorilla TSDB
		metricsMu.Lock()
		storedTimes = append(storedTimes, time.Now().Unix())
		if len(storedTimes) > 200 {
			storedTimes = storedTimes[1:]
		}

		// Calculate total CPU consumption
		var totalCPU = 5.0
		for _, c := range state.Containers {
			if c.Status == "Running" {
				totalCPU += float64(c.CPUCores) * 8.5
			}
		}
		storedCPUs = append(storedCPUs, totalCPU)
		if len(storedCPUs) > 200 {
			storedCPUs = storedCPUs[1:]
		}
		metricsMu.Unlock()

		balance := state.Balance
		rate := state.BillingRate
		state.mu.Unlock()

		// Broadcast billing update to SSE clients
		billingMsg := map[string]interface{}{
			"type": "billing_update",
			"data": map[string]interface{}{
				"balance":      balance,
				"billing_rate": rate,
			},
		}
		jsonBytes, err := json.Marshal(billingMsg)
		if err == nil {
			broker.messages <- string(jsonBytes)
		}
	}
}
