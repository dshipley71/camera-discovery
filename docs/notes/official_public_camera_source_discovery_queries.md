# Official Public Camera Source-Discovery Queries

These queries are intended to find curated public-facing camera pages from government, transportation, education, airport, park, port, and official tourism sources — not exposed device interfaces.

Replace `[LOCATION]` with a city, county, state, region, airport, park, or agency name.

## General official public camera pages

```text
"public cameras" "[LOCATION]" site:.gov
"live cameras" "[LOCATION]" site:.gov
"camera map" "[LOCATION]" site:.gov
"camera locations" "[LOCATION]" site:.gov
"webcam map" "[LOCATION]" site:.gov
"live webcam" "[LOCATION]" site:.gov
"webcams" "[LOCATION]" site:.gov
"camera feeds" "[LOCATION]" site:.gov
"public webcam" "[LOCATION]" site:.gov
"live camera" "[LOCATION]" "official"
```

## Traffic / DOT / 511 cameras

```text
"traffic cameras" "[LOCATION]" site:.gov
"live traffic cameras" "[LOCATION]" site:.gov
"road cameras" "[LOCATION]" site:.gov
"highway cameras" "[LOCATION]" site:.gov
"freeway cameras" "[LOCATION]" site:.gov
"511 cameras" "[LOCATION]" site:.gov
"511 traffic cameras" "[LOCATION]" site:.gov
"traveler information" "cameras" "[LOCATION]" site:.gov
"DOT cameras" "[LOCATION]" site:.gov
"department of transportation" "cameras" "[LOCATION]" site:.gov
"traffic camera map" "[LOCATION]" site:.gov
"road conditions" "cameras" "[LOCATION]" site:.gov
"winter road cameras" "[LOCATION]" site:.gov
"highway travel cameras" "[LOCATION]" site:.gov
```

## Weather cameras

```text
"weather cameras" "[LOCATION]" site:.gov
"weather camera" "[LOCATION]" site:.gov
"live weather camera" "[LOCATION]" site:.gov
"weather webcam" "[LOCATION]" site:.gov
"meteorological camera" "[LOCATION]" site:.gov
"airport weather camera" "[LOCATION]" site:.gov
"surface weather camera" "[LOCATION]" site:.gov
"road weather cameras" "[LOCATION]" site:.gov
"weather cameras" "[LOCATION]" site:.edu
"webcam" "weather" "[LOCATION]" site:.edu
```

## Airport / aviation cameras

```text
"airport cameras" "[LOCATION]" site:.gov
"airport weather camera" "[LOCATION]" site:.gov
"aviation weather camera" "[LOCATION]" site:.gov
"runway camera" "[LOCATION]" site:.gov
"airport webcam" "[LOCATION]" site:.gov
"terminal camera" "[LOCATION]" site:.gov
"airport live camera" "[LOCATION]" site:.gov
"airfield camera" "[LOCATION]" site:.gov
"aviation camera program" "[LOCATION]" site:.gov
```

## Beach / surf / coastal cameras

```text
"beach cameras" "[LOCATION]" site:.gov
"beach webcam" "[LOCATION]" site:.gov
"surf camera" "[LOCATION]" site:.gov
"surf cam" "[LOCATION]" site:.gov
"coastal cameras" "[LOCATION]" site:.gov
"shoreline camera" "[LOCATION]" site:.gov
"pier camera" "[LOCATION]" site:.gov
"ocean camera" "[LOCATION]" site:.gov
"beach conditions" "camera" "[LOCATION]" site:.gov
```

## Harbor / port / marina cameras

```text
"harbor cameras" "[LOCATION]" site:.gov
"port cameras" "[LOCATION]" site:.gov
"marina cameras" "[LOCATION]" site:.gov
"harbor webcam" "[LOCATION]" site:.gov
"port webcam" "[LOCATION]" site:.gov
"marina webcam" "[LOCATION]" site:.gov
"ship channel camera" "[LOCATION]" site:.gov
"waterfront camera" "[LOCATION]" site:.gov
"ferry terminal camera" "[LOCATION]" site:.gov
"marine traffic camera" "[LOCATION]" site:.gov
```

## Parks / public lands / wildlife cameras

```text
"park cameras" "[LOCATION]" site:.gov
"park webcam" "[LOCATION]" site:.gov
"live park camera" "[LOCATION]" site:.gov
"wildlife camera" "[LOCATION]" site:.gov
"wildlife webcam" "[LOCATION]" site:.gov
"trail camera" "[LOCATION]" site:.gov
"visitor center webcam" "[LOCATION]" site:.gov
"national park webcam" "[LOCATION]" site:.gov
"state park webcam" "[LOCATION]" site:.gov
"public lands camera" "[LOCATION]" site:.gov
```

## Mountain / ski / snow cameras

```text
"mountain cameras" "[LOCATION]" site:.gov
"mountain webcam" "[LOCATION]" site:.gov
"snow camera" "[LOCATION]" site:.gov
"snow cameras" "[LOCATION]" site:.gov
"ski camera" "[LOCATION]" site:.gov
"ski webcam" "[LOCATION]" site:.gov
"pass camera" "[LOCATION]" site:.gov
"mountain pass camera" "[LOCATION]" site:.gov
"avalanche camera" "[LOCATION]" site:.gov
```

## Campus / university cameras

```text
"campus webcam" "[LOCATION]" site:.edu
"campus cameras" "[LOCATION]" site:.edu
"live campus camera" "[LOCATION]" site:.edu
"university webcam" "[LOCATION]" site:.edu
"college webcam" "[LOCATION]" site:.edu
"campus live cam" "[LOCATION]" site:.edu
"weather camera" "[LOCATION]" site:.edu
"webcam" "campus" "[LOCATION]" site:.edu
```

## City / civic / downtown cameras

```text
"city webcam" "[LOCATION]" site:.gov
"downtown camera" "[LOCATION]" site:.gov
"downtown webcam" "[LOCATION]" site:.gov
"public square camera" "[LOCATION]" site:.gov
"city camera" "[LOCATION]" site:.gov
"municipal camera" "[LOCATION]" site:.gov
"public works camera" "[LOCATION]" site:.gov
"city live camera" "[LOCATION]" site:.gov
```

## Construction / infrastructure project cameras

```text
"construction camera" "[LOCATION]" site:.gov
"construction cameras" "[LOCATION]" site:.gov
"project camera" "[LOCATION]" site:.gov
"project webcam" "[LOCATION]" site:.gov
"bridge construction camera" "[LOCATION]" site:.gov
"road project camera" "[LOCATION]" site:.gov
"capital project camera" "[LOCATION]" site:.gov
"infrastructure camera" "[LOCATION]" site:.gov
```

## Public safety / emergency management cameras

```text
"emergency management" "camera" "[LOCATION]" site:.gov
"public safety camera" "[LOCATION]" site:.gov
"flood camera" "[LOCATION]" site:.gov
"river camera" "[LOCATION]" site:.gov
"dam camera" "[LOCATION]" site:.gov
"evacuation route camera" "[LOCATION]" site:.gov
"fire weather camera" "[LOCATION]" site:.gov
"disaster camera" "[LOCATION]" site:.gov
```

## Official tourism / chamber / destination camera pages

Use these more cautiously than `.gov` / `.edu`, but they can help find intentionally public destination webcams.

```text
"official visitor" "webcam" "[LOCATION]"
"official tourism" "webcam" "[LOCATION]"
"visitor bureau" "webcam" "[LOCATION]"
"tourism" "live camera" "[LOCATION]"
"chamber of commerce" "webcam" "[LOCATION]"
"destination webcam" "[LOCATION]" "official"
"live camera" "[LOCATION]" "visitor center"
```

## Safe exclusion filters

```text
"traffic cameras" "[LOCATION]" site:.gov -site:insecam.org -site:shodan.io -site:censys.io -site:zoomeye.org -site:fofa.info
"live cameras" "[LOCATION]" site:.gov -site:insecam.org -site:shodan.io -site:censys.io -site:zoomeye.org -site:fofa.info
"weather cameras" "[LOCATION]" site:.edu -site:insecam.org -site:shodan.io -site:censys.io -site:zoomeye.org -site:fofa.info
"public webcam" "[LOCATION]" site:.gov -site:insecam.org -site:shodan.io -site:censys.io -site:zoomeye.org -site:fofa.info
```

## Recommended camera-discovery use

Use these as source-discovery seeds. The pipeline should find official directory pages first, confirm the source is allowed, then extract structured public camera records or public-facing media links from those pages.
