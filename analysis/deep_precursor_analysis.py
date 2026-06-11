#!/usr/bin/env python3
"""
Deep Precursor Pattern Analysis
================================
Analyzes 59 movers to identify:
  1. Common precursor indicators (10+ patterns)
  2. Pair characteristics (symbol types, market cap tiers)
  3. Time-of-day patterns (when do moves happen?)
  4. Movement clustering (consecutive vs waves)
  5. Pair groupings and cataloging
  6. Indicator correlations and combinations

Output: deep_precursor_insights.json + PRECURSOR_PATTERNS.md

Usage:
  python analysis/deep_precursor_analysis.py
"""

import sys
import os
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict, Counter

# Fix Windows console encoding
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ─── CONFIGURATION ───────────────────────────────────────────────────────────

INPUT_FILE = "226_movers_precursors.json"
OUTPUT_FILE = "deep_precursor_insights.json"
MARKDOWN_FILE = "PRECURSOR_PATTERNS.md"

# ─── PATTERN DETECTION FUNCTIONS ─────────────────────────────────────────────

def analyze_rsi_patterns(precursors, direction):
    """Analyze RSI precursor patterns"""
    patterns = {
        'extreme_oversold': 0,  # RSI < 20
        'oversold': 0,           # RSI 20-30
        'neutral_low': 0,        # RSI 30-45
        'neutral': 0,            # RSI 45-55
        'neutral_high': 0,       # RSI 55-70
        'overbought': 0,         # RSI 70-80
        'extreme_overbought': 0, # RSI > 80
    }

    for candle in precursors:
        rsi = candle.get('rsi')
        if rsi is None:
            continue

        if rsi < 20:
            patterns['extreme_oversold'] += 1
        elif rsi < 30:
            patterns['oversold'] += 1
        elif rsi < 45:
            patterns['neutral_low'] += 1
        elif rsi < 55:
            patterns['neutral'] += 1
        elif rsi < 70:
            patterns['neutral_high'] += 1
        elif rsi < 80:
            patterns['overbought'] += 1
        else:
            patterns['extreme_overbought'] += 1

    return patterns


def analyze_bb_patterns(precursors, direction):
    """Analyze Bollinger Band %B patterns"""
    patterns = {
        'below_lower': 0,      # %B < 0 (below lower band)
        'near_lower': 0,       # %B 0-0.2
        'lower_third': 0,      # %B 0.2-0.4
        'middle': 0,           # %B 0.4-0.6
        'upper_third': 0,      # %B 0.6-0.8
        'near_upper': 0,       # %B 0.8-1.0
        'above_upper': 0,      # %B > 1.0 (above upper band)
    }

    for candle in precursors:
        bb = candle.get('bb_pct_b')
        if bb is None:
            continue

        if bb < 0:
            patterns['below_lower'] += 1
        elif bb < 0.2:
            patterns['near_lower'] += 1
        elif bb < 0.4:
            patterns['lower_third'] += 1
        elif bb < 0.6:
            patterns['middle'] += 1
        elif bb < 0.8:
            patterns['upper_third'] += 1
        elif bb <= 1.0:
            patterns['near_upper'] += 1
        else:
            patterns['above_upper'] += 1

    return patterns


def analyze_zscore_patterns(precursors, direction):
    """Analyze Z-score patterns"""
    patterns = {
        'extreme_negative': 0,  # Z < -2.5 (very oversold)
        'high_negative': 0,     # Z -2.5 to -1.5
        'moderate_negative': 0, # Z -1.5 to -0.5
        'neutral': 0,           # Z -0.5 to 0.5
        'moderate_positive': 0, # Z 0.5 to 1.5
        'high_positive': 0,     # Z 1.5 to 2.5
        'extreme_positive': 0,  # Z > 2.5 (very overbought)
    }

    for candle in precursors:
        z = candle.get('zscore')
        if z is None:
            continue

        if z < -2.5:
            patterns['extreme_negative'] += 1
        elif z < -1.5:
            patterns['high_negative'] += 1
        elif z < -0.5:
            patterns['moderate_negative'] += 1
        elif z < 0.5:
            patterns['neutral'] += 1
        elif z < 1.5:
            patterns['moderate_positive'] += 1
        elif z < 2.5:
            patterns['high_positive'] += 1
        else:
            patterns['extreme_positive'] += 1

    return patterns


def analyze_volume_patterns(precursors, direction):
    """Analyze volume ratio patterns"""
    patterns = {
        'very_low': 0,      # Vol < 0.5x avg
        'low': 0,           # Vol 0.5-0.8x avg
        'normal': 0,        # Vol 0.8-1.2x avg
        'elevated': 0,      # Vol 1.2-2.0x avg
        'high': 0,          # Vol 2.0-3.0x avg
        'very_high': 0,     # Vol > 3.0x avg
    }

    for candle in precursors:
        vol = candle.get('volume_ratio')
        if vol is None:
            continue

        if vol < 0.5:
            patterns['very_low'] += 1
        elif vol < 0.8:
            patterns['low'] += 1
        elif vol < 1.2:
            patterns['normal'] += 1
        elif vol < 2.0:
            patterns['elevated'] += 1
        elif vol < 3.0:
            patterns['high'] += 1
        else:
            patterns['very_high'] += 1

    return patterns


def analyze_squeeze_patterns(precursors, direction):
    """Analyze Bollinger Squeeze patterns"""
    patterns = {
        'tight_squeeze': 0,      # Squeeze < 0.5 (very tight)
        'squeeze_on': 0,         # Squeeze 0.5-1.0 (BB inside KC)
        'neutral': 0,            # Squeeze 1.0-1.5
        'squeeze_off': 0,        # Squeeze 1.5-2.5 (BB outside KC)
        'expanding': 0,          # Squeeze 2.5-4.0 (volatility expanding)
        'very_volatile': 0,      # Squeeze > 4.0
    }

    for candle in precursors:
        sq = candle.get('squeeze_ratio')
        if sq is None:
            continue

        if sq < 0.5:
            patterns['tight_squeeze'] += 1
        elif sq < 1.0:
            patterns['squeeze_on'] += 1
        elif sq < 1.5:
            patterns['neutral'] += 1
        elif sq < 2.5:
            patterns['squeeze_off'] += 1
        elif sq < 4.0:
            patterns['expanding'] += 1
        else:
            patterns['very_volatile'] += 1

    return patterns


def analyze_atr_patterns(precursors, direction):
    """Analyze ATR% patterns"""
    patterns = {
        'very_low_volatility': 0,  # ATR < 0.5%
        'low_volatility': 0,       # ATR 0.5-1.0%
        'normal_volatility': 0,    # ATR 1.0-2.0%
        'elevated_volatility': 0,  # ATR 2.0-4.0%
        'high_volatility': 0,      # ATR 4.0-8.0%
        'extreme_volatility': 0,   # ATR > 8.0%
    }

    for candle in precursors:
        atr = candle.get('atr_pct')
        if atr is None:
            continue

        if atr < 0.5:
            patterns['very_low_volatility'] += 1
        elif atr < 1.0:
            patterns['low_volatility'] += 1
        elif atr < 2.0:
            patterns['normal_volatility'] += 1
        elif atr < 4.0:
            patterns['elevated_volatility'] += 1
        elif atr < 8.0:
            patterns['high_volatility'] += 1
        else:
            patterns['extreme_volatility'] += 1

    return patterns


def detect_divergence_pattern(precursors, direction):
    """Detect price-indicator divergence patterns"""
    if len(precursors) < 4:
        return False

    # Check if price making lower lows but RSI making higher lows (bullish divergence)
    # or price making higher highs but RSI making lower highs (bearish divergence)

    prices = [c['close'] for c in precursors if c.get('close')]
    rsis = [c['rsi'] for c in precursors if c.get('rsi')]

    if len(prices) < 4 or len(rsis) < 4:
        return False

    # Bullish divergence: price down, RSI up
    price_trend_down = prices[-1] < prices[0] and prices[-2] < prices[1]
    rsi_trend_up = rsis[-1] > rsis[0] and rsis[-2] > rsis[1]

    # Bearish divergence: price up, RSI down
    price_trend_up = prices[-1] > prices[0] and prices[-2] > prices[1]
    rsi_trend_down = rsis[-1] < rsis[0] and rsis[-2] < rsis[1]

    if direction == "UP" and price_trend_down and rsi_trend_up:
        return "bullish_divergence"
    elif direction == "DOWN" and price_trend_up and rsi_trend_down:
        return "bearish_divergence"

    return False


def detect_volatility_compression(precursors):
    """Detect volatility compression (squeeze before breakout)"""
    if len(precursors) < 4:
        return False

    # Check if ATR% declining in precursor candles
    atrs = [c.get('atr_pct') for c in precursors if c.get('atr_pct')]

    if len(atrs) < 4:
        return False

    # Check if ATR declining (compression)
    first_half_avg = sum(atrs[:3]) / 3
    second_half_avg = sum(atrs[3:]) / 3

    return second_half_avg < first_half_avg * 0.85  # 15% decline


def detect_volume_surge_pattern(precursors):
    """Detect volume surge in final candle"""
    if len(precursors) < 2:
        return False

    final_vol = precursors[-1].get('volume_ratio')
    avg_vol = sum(c.get('volume_ratio', 0) for c in precursors[:-1]) / (len(precursors) - 1)

    if final_vol is None or avg_vol == 0:
        return False

    return final_vol > avg_vol * 2.0  # 2× volume spike in final candle


def categorize_symbol(symbol):
    """Categorize symbol by type"""
    symbol = symbol.upper().replace('USDT', '').replace('USDC', '')

    # Known categories
    if symbol in ['BTC', 'ETH', 'BNB', 'XRP', 'SOL', 'ADA', 'DOGE', 'MATIC', 'DOT', 'AVAX']:
        return 'large_cap'

    # Check for meme/community tokens
    meme_keywords = ['DOGE', 'SHIB', 'PEPE', 'FLOKI', 'SHIBARIUM', 'CAT', 'DOG', 'MEME',
                     'MOON', 'ELON', 'BABY', 'INU', 'WOJAK', 'CHAD']
    if any(kw in symbol for kw in meme_keywords):
        return 'meme'

    # Check for AI/tech tokens
    ai_keywords = ['AI', 'AGI', 'AGENT', 'NEURAL', 'BOT', 'GPT', 'CHAT']
    if any(kw in symbol for kw in ai_keywords):
        return 'ai_tech'

    # Check for DeFi tokens
    defi_keywords = ['SWAP', 'DEFI', 'YIELD', 'FARM', 'POOL', 'VAULT', 'STAKE']
    if any(kw in symbol for kw in defi_keywords):
        return 'defi'

    # Check for gaming/metaverse
    gaming_keywords = ['GAME', 'PLAY', 'META', 'VERSE', 'NFT', 'LAND', 'WORLD']
    if any(kw in symbol for kw in gaming_keywords):
        return 'gaming'

    # Default to mid/small cap
    return 'mid_small_cap'


def analyze_time_patterns(movers):
    """Analyze when moves occur (time of day)"""
    hours = []

    for mover in movers:
        timestamp = mover['move_metadata']['timestamp']
        dt = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
        hours.append(dt.hour)

    hour_counts = Counter(hours)

    # Categorize by time periods
    time_periods = {
        'asia_morning': 0,    # 00:00-04:00 UTC
        'asia_afternoon': 0,  # 04:00-08:00 UTC
        'europe_morning': 0,  # 08:00-12:00 UTC
        'europe_afternoon': 0,# 12:00-16:00 UTC
        'us_morning': 0,      # 16:00-20:00 UTC
        'us_evening': 0,      # 20:00-24:00 UTC
    }

    for hour, count in hour_counts.items():
        if 0 <= hour < 4:
            time_periods['asia_morning'] += count
        elif 4 <= hour < 8:
            time_periods['asia_afternoon'] += count
        elif 8 <= hour < 12:
            time_periods['europe_morning'] += count
        elif 12 <= hour < 16:
            time_periods['europe_afternoon'] += count
        elif 16 <= hour < 20:
            time_periods['us_morning'] += count
        else:
            time_periods['us_evening'] += count

    return hour_counts, time_periods


def analyze_movement_clustering(movers):
    """Analyze if movements occur consecutively or in waves"""
    # Sort by timestamp
    sorted_movers = sorted(movers, key=lambda x: x['move_metadata']['timestamp'])

    # Calculate time gaps between moves
    gaps = []
    for i in range(1, len(sorted_movers)):
        prev_time = sorted_movers[i-1]['move_metadata']['timestamp']
        curr_time = sorted_movers[i]['move_metadata']['timestamp']
        gap_minutes = (curr_time - prev_time) / 1000 / 60
        gaps.append(gap_minutes)

    # Categorize gaps
    gap_categories = {
        'immediate': 0,      # < 5 min (same wave)
        'short': 0,          # 5-15 min
        'medium': 0,         # 15-60 min
        'long': 0,           # 1-3 hours
        'very_long': 0,      # > 3 hours
    }

    for gap in gaps:
        if gap < 5:
            gap_categories['immediate'] += 1
        elif gap < 15:
            gap_categories['short'] += 1
        elif gap < 60:
            gap_categories['medium'] += 1
        elif gap < 180:
            gap_categories['long'] += 1
        else:
            gap_categories['very_long'] += 1

    # Detect waves (clusters of moves within 30 min)
    waves = []
    current_wave = [sorted_movers[0]]

    for i in range(1, len(sorted_movers)):
        gap = gaps[i-1]
        if gap < 30:  # Part of same wave
            current_wave.append(sorted_movers[i])
        else:  # Start new wave
            if len(current_wave) >= 2:
                waves.append(current_wave)
            current_wave = [sorted_movers[i]]

    if len(current_wave) >= 2:
        waves.append(current_wave)

    return gap_categories, waves, gaps


def analyze_directional_clusters(movers):
    """Analyze if UP/DOWN moves cluster together"""
    sorted_movers = sorted(movers, key=lambda x: x['move_metadata']['timestamp'])
    directions = [m['move_metadata']['direction'] for m in sorted_movers]

    # Find consecutive same-direction runs
    runs = []
    current_run = [directions[0]]

    for i in range(1, len(directions)):
        if directions[i] == current_run[-1]:
            current_run.append(directions[i])
        else:
            if len(current_run) >= 2:
                runs.append((current_run[0], len(current_run)))
            current_run = [directions[i]]

    if len(current_run) >= 2:
        runs.append((current_run[0], len(current_run)))

    return runs


def load_precursor_data(filepath):
    """Load precursor data from JSON"""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data['movers']


def save_results(results, filepath):
    """Save analysis results to JSON"""
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2)
    print(f"\n✓ Results saved to: {filepath}")


def generate_markdown_report(results, filepath):
    """Generate comprehensive markdown report"""
    md = []

    md.append("# Precursor Pattern Analysis - Deep Insights")
    md.append("")
    md.append("**Analysis Date**: " + datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'))
    md.append("")
    md.append("---")
    md.append("")

    # Overview
    md.append("## Executive Summary")
    md.append("")
    md.append(f"Analyzed **{results['total_movers']}** movers with 10%+ price changes.")
    md.append(f"- **UP moves**: {results['directional_split']['UP']}")
    md.append(f"- **DOWN moves**: {results['directional_split']['DOWN']}")
    md.append("")

    # 10+ Precursor Indicators
    md.append("## 🎯 Top 10+ Precursor Indicators")
    md.append("")
    md.append("### What Happens Before Major Moves?")
    md.append("")

    for idx, pattern in enumerate(results['top_precursor_patterns'], 1):
        md.append(f"### {idx}. {pattern['name']}")
        md.append(f"**Frequency**: {pattern['frequency']}%")
        md.append(f"**Description**: {pattern['description']}")
        md.append("")

    # Symbol categorization
    md.append("## 📊 Symbol Categorization")
    md.append("")
    md.append("### What Types of Pairs Move?")
    md.append("")
    md.append("| Category | Count | Percentage | Examples |")
    md.append("|----------|-------|------------|----------|")

    for cat, data in sorted(results['symbol_categories'].items(),
                           key=lambda x: x[1]['count'], reverse=True):
        examples = ', '.join(data['examples'][:3])
        md.append(f"| {cat} | {data['count']} | {data['percentage']:.1f}% | {examples} |")

    md.append("")

    # Time patterns
    md.append("## ⏰ Time-of-Day Patterns")
    md.append("")
    md.append("### When Do Moves Occur?")
    md.append("")
    md.append("| Time Period | Moves | Percentage |")
    md.append("|-------------|-------|------------|")

    for period, count in results['time_periods'].items():
        pct = count / results['total_movers'] * 100
        md.append(f"| {period.replace('_', ' ').title()} | {count} | {pct:.1f}% |")

    md.append("")
    md.append("**Peak Hours**: " + results['peak_hours'])
    md.append("")

    # Movement clustering
    md.append("## 🌊 Movement Clustering Patterns")
    md.append("")
    md.append("### Are Movements Consecutive or in Waves?")
    md.append("")
    md.append(f"- **Total Waves Detected**: {results['wave_analysis']['wave_count']}")
    md.append(f"- **Average Wave Size**: {results['wave_analysis']['avg_wave_size']:.1f} moves")
    md.append(f"- **Largest Wave**: {results['wave_analysis']['largest_wave']} moves")
    md.append("")
    md.append("**Time Gaps Between Moves**:")
    md.append("")
    md.append("| Gap Category | Count | Percentage |")
    md.append("|--------------|-------|------------|")

    for gap, count in results['gap_analysis'].items():
        pct = count / sum(results['gap_analysis'].values()) * 100
        md.append(f"| {gap.replace('_', ' ').title()} | {count} | {pct:.1f}% |")

    md.append("")
    md.append(f"**Pattern**: {results['clustering_pattern']}")
    md.append("")

    # Directional clustering
    md.append("## 📈📉 Directional Clustering")
    md.append("")
    md.append("### Do UP/DOWN Moves Cluster Together?")
    md.append("")

    if results['directional_runs']:
        md.append("**Longest Consecutive Runs**:")
        md.append("")
        for direction, length in results['directional_runs'][:5]:
            md.append(f"- {length} consecutive {direction} moves")
        md.append("")

    md.append(f"**Pattern**: {results['directional_clustering_pattern']}")
    md.append("")

    # Write markdown
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(md))

    print(f"✓ Markdown report saved to: {filepath}")


def main():
    input_path = Path(__file__).parent / INPUT_FILE
    output_path = Path(__file__).parent / OUTPUT_FILE
    markdown_path = Path(__file__).parent / MARKDOWN_FILE

    print("=" * 80)
    print("DEEP PRECURSOR PATTERN ANALYSIS")
    print("=" * 80)

    # Load data
    print(f"\nLoading precursor data from: {input_path}")
    movers = load_precursor_data(input_path)
    print(f"Loaded {len(movers)} movers\n")

    # Initialize results
    results = {
        'total_movers': len(movers),
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'directional_split': {'UP': 0, 'DOWN': 0},
        'top_precursor_patterns': [],
        'symbol_categories': {},
        'time_patterns': {},
        'time_periods': {},
        'peak_hours': '',
        'wave_analysis': {},
        'gap_analysis': {},
        'clustering_pattern': '',
        'directional_runs': [],
        'directional_clustering_pattern': '',
    }

    # Count directional split
    for mover in movers:
        direction = mover['move_metadata']['direction']
        results['directional_split'][direction] += 1

    print("Analyzing patterns...")
    print("-" * 80)

    # Analyze each mover's precursors
    all_patterns = []
    symbol_categories = defaultdict(lambda: {'count': 0, 'examples': []})

    for mover in movers:
        symbol = mover['symbol']
        direction = mover['move_metadata']['direction']
        precursors = mover['precursor_candles']

        # Categorize symbol
        category = categorize_symbol(symbol)
        symbol_categories[category]['count'] += 1
        if len(symbol_categories[category]['examples']) < 5:
            symbol_categories[category]['examples'].append(symbol)

        # Analyze patterns for this mover
        rsi_patterns = analyze_rsi_patterns(precursors, direction)
        bb_patterns = analyze_bb_patterns(precursors, direction)
        z_patterns = analyze_zscore_patterns(precursors, direction)
        vol_patterns = analyze_volume_patterns(precursors, direction)
        squeeze_patterns = analyze_squeeze_patterns(precursors, direction)
        atr_patterns = analyze_atr_patterns(precursors, direction)

        divergence = detect_divergence_pattern(precursors, direction)
        volatility_compression = detect_volatility_compression(precursors)
        volume_surge = detect_volume_surge_pattern(precursors)

        all_patterns.append({
            'symbol': symbol,
            'direction': direction,
            'rsi': rsi_patterns,
            'bb': bb_patterns,
            'zscore': z_patterns,
            'volume': vol_patterns,
            'squeeze': squeeze_patterns,
            'atr': atr_patterns,
            'divergence': divergence,
            'volatility_compression': volatility_compression,
            'volume_surge': volume_surge,
        })

    # Compile top patterns
    print("\n1. Compiling top precursor indicators...")

    # Calculate pattern frequencies
    pattern_freq = {
        'Extreme Volatility (ATR > 4%)': 0,
        'Volatility Compression Before Breakout': 0,
        'Volume Surge in Final Candle (2× avg)': 0,
        'RSI Oversold (< 30)': 0,
        'RSI Overbought (> 70)': 0,
        'BB Below Lower Band': 0,
        'BB Above Upper Band': 0,
        'Z-Score Extreme (|Z| > 2.0)': 0,
        'Squeeze On (BB inside KC)': 0,
        'Expanding Volatility (Squeeze > 2.5)': 0,
        'Bullish/Bearish Divergence': 0,
        'Low Volume (< 0.8× avg)': 0,
    }

    for p in all_patterns:
        # ATR patterns
        if p['atr']['high_volatility'] > 0 or p['atr']['extreme_volatility'] > 0:
            pattern_freq['Extreme Volatility (ATR > 4%)'] += 1

        # Compression
        if p['volatility_compression']:
            pattern_freq['Volatility Compression Before Breakout'] += 1

        # Volume surge
        if p['volume_surge']:
            pattern_freq['Volume Surge in Final Candle (2× avg)'] += 1

        # RSI
        if p['rsi']['oversold'] > 0 or p['rsi']['extreme_oversold'] > 0:
            pattern_freq['RSI Oversold (< 30)'] += 1
        if p['rsi']['overbought'] > 0 or p['rsi']['extreme_overbought'] > 0:
            pattern_freq['RSI Overbought (> 70)'] += 1

        # BB
        if p['bb']['below_lower'] > 0:
            pattern_freq['BB Below Lower Band'] += 1
        if p['bb']['above_upper'] > 0:
            pattern_freq['BB Above Upper Band'] += 1

        # Z-score
        if p['zscore']['extreme_negative'] > 0 or p['zscore']['high_negative'] > 0 or \
           p['zscore']['extreme_positive'] > 0 or p['zscore']['high_positive'] > 0:
            pattern_freq['Z-Score Extreme (|Z| > 2.0)'] += 1

        # Squeeze
        if p['squeeze']['squeeze_on'] > 0 or p['squeeze']['tight_squeeze'] > 0:
            pattern_freq['Squeeze On (BB inside KC)'] += 1
        if p['squeeze']['expanding'] > 0 or p['squeeze']['very_volatile'] > 0:
            pattern_freq['Expanding Volatility (Squeeze > 2.5)'] += 1

        # Divergence
        if p['divergence']:
            pattern_freq['Bullish/Bearish Divergence'] += 1

        # Low volume
        if p['volume']['low'] > 0 or p['volume']['very_low'] > 0:
            pattern_freq['Low Volume (< 0.8× avg)'] += 1

    # Sort by frequency
    top_patterns = []
    for name, count in sorted(pattern_freq.items(), key=lambda x: x[1], reverse=True):
        freq_pct = count / len(movers) * 100

        # Add descriptions
        descriptions = {
            'Extreme Volatility (ATR > 4%)': 'High ATR indicates recent large price swings, suggesting pair is "hot" and primed for more movement',
            'Volatility Compression Before Breakout': 'ATR declining in precursor candles (compression), then explosive breakout',
            'Volume Surge in Final Candle (2× avg)': 'Sudden 2×+ volume spike in the candle immediately before the move - strong entry signal',
            'RSI Oversold (< 30)': 'RSI below 30 suggests oversold conditions, potential mean-reversion bounce',
            'RSI Overbought (> 70)': 'RSI above 70 suggests overbought conditions, potential mean-reversion drop',
            'BB Below Lower Band': 'Price broke below lower Bollinger Band - extreme oversold, likely bounce',
            'BB Above Upper Band': 'Price broke above upper Bollinger Band - extreme overbought, likely pullback',
            'Z-Score Extreme (|Z| > 2.0)': 'Price is 2+ standard deviations from mean - statistically significant deviation',
            'Squeeze On (BB inside KC)': 'Bollinger Bands compressed inside Keltner Channels - volatility building up for breakout',
            'Expanding Volatility (Squeeze > 2.5)': 'Bollinger Bands expanding rapidly - volatility breaking out',
            'Bullish/Bearish Divergence': 'Price and indicator moving in opposite directions - reversal signal',
            'Low Volume (< 0.8× avg)': 'Below-average volume before move - breakout occurs on low liquidity',
        }

        top_patterns.append({
            'name': name,
            'frequency': round(freq_pct, 1),
            'count': count,
            'description': descriptions.get(name, 'No description')
        })

    results['top_precursor_patterns'] = top_patterns

    # Symbol categories
    print("2. Categorizing symbols...")
    for category, data in symbol_categories.items():
        data['percentage'] = data['count'] / len(movers) * 100
    results['symbol_categories'] = dict(symbol_categories)

    # Time patterns
    print("3. Analyzing time-of-day patterns...")
    hour_counts, time_periods = analyze_time_patterns(movers)
    results['time_patterns'] = dict(hour_counts)
    results['time_periods'] = time_periods

    # Find peak hours
    top_hours = sorted(hour_counts.items(), key=lambda x: x[1], reverse=True)[:3]
    results['peak_hours'] = ', '.join([f"{h:02d}:00 UTC ({c} moves)" for h, c in top_hours])

    # Movement clustering
    print("4. Analyzing movement clustering...")
    gap_categories, waves, gaps = analyze_movement_clustering(movers)

    results['gap_analysis'] = gap_categories
    results['wave_analysis'] = {
        'wave_count': len(waves),
        'avg_wave_size': sum(len(w) for w in waves) / len(waves) if waves else 0,
        'largest_wave': max(len(w) for w in waves) if waves else 0,
    }

    # Determine clustering pattern
    immediate_pct = gap_categories['immediate'] / sum(gap_categories.values()) * 100
    if immediate_pct > 40:
        results['clustering_pattern'] = "Highly clustered - moves occur in rapid waves"
    elif immediate_pct > 20:
        results['clustering_pattern'] = "Moderately clustered - some wave patterns"
    else:
        results['clustering_pattern'] = "Distributed - moves spread throughout the day"

    # Directional clustering
    print("5. Analyzing directional clustering...")
    directional_runs = analyze_directional_clusters(movers)
    results['directional_runs'] = sorted(directional_runs, key=lambda x: x[1], reverse=True)

    if directional_runs and max(r[1] for r in directional_runs) >= 4:
        results['directional_clustering_pattern'] = "Strong directional clustering - moves follow market momentum"
    elif directional_runs and max(r[1] for r in directional_runs) >= 3:
        results['directional_clustering_pattern'] = "Moderate directional clustering"
    else:
        results['directional_clustering_pattern'] = "Random directional distribution - no clear clustering"

    # Save results
    print("\n" + "=" * 80)
    print("ANALYSIS COMPLETE")
    print("=" * 80)

    save_results(results, output_path)
    generate_markdown_report(results, markdown_path)

    # Print summary
    print("\n" + "=" * 80)
    print("KEY FINDINGS SUMMARY")
    print("=" * 80)

    print(f"\n📊 Symbol Types:")
    for cat, data in sorted(results['symbol_categories'].items(),
                           key=lambda x: x[1]['count'], reverse=True):
        print(f"  {cat:20} {data['count']:3d} ({data['percentage']:5.1f}%)")

    print(f"\n⏰ Peak Trading Hours:")
    print(f"  {results['peak_hours']}")

    print(f"\n🌊 Movement Pattern:")
    print(f"  {results['clustering_pattern']}")
    print(f"  Waves detected: {results['wave_analysis']['wave_count']}")
    print(f"  Avg wave size: {results['wave_analysis']['avg_wave_size']:.1f} moves")

    print(f"\n📈 Directional Pattern:")
    print(f"  {results['directional_clustering_pattern']}")

    print("\n✓ Analysis complete!")
    print(f"✓ Full report saved to: {markdown_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
