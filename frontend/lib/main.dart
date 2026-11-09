import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'api.dart';

/// Purchase Intelligence by TAIG ITS — Flutter UI, single user, no AI.
/// 4 screens, in order: Snap, Review & Confirm, Pantry, Analytics.
/// Backend: Droplet PIA API (see api.dart). Certs null for the demo.
void main() => runApp(const PiaApp());

class PiaApp extends StatelessWidget {
  const PiaApp({super.key});
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Purchase Intelligence',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF7A9A7E)),
        scaffoldBackgroundColor: const Color(0xFFDBD5C9),
        cardColor: const Color(0xFFF5F0E6),
        useMaterial3: true,
      ),
      home: const HomePage(),
    );
  }
}

class HomePage extends StatefulWidget {
  const HomePage({super.key});
  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  final api = PiaApi();
  int _tab = 0;
  Map<String, dynamic>? _extraction;

  @override
  Widget build(BuildContext context) {
    final pages = <Widget>[
      ScanScreen(api: api, onExtracted: (e) => setState(() {
            _extraction = e;
            _tab = 1;
          })),
      ReviewScreen(api: api, extraction: _extraction),
      PantryScreen(api: api),
      AnalyticsScreen(api: api),
    ];
    return Scaffold(
      appBar: AppBar(title: const Text('Purchase Intelligence\nby TAIG ITS')),
      body: pages[_tab],
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) => setState(() => _tab = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.camera_alt), label: 'Scan'),
          NavigationDestination(icon: Icon(Icons.checklist), label: 'Review'),
          NavigationDestination(icon: Icon(Icons.kitchen), label: 'Pantry'),
          NavigationDestination(icon: Icon(Icons.bar_chart), label: 'Analytics'),
        ],
      ),
    );
  }
}

class ScanScreen extends StatefulWidget {
  const ScanScreen({super.key, required this.api, required this.onExtracted});
  final PiaApi api;
  final void Function(Map<String, dynamic>) onExtracted;
  @override
  State<ScanScreen> createState() => _ScanScreenState();
}

class _ScanScreenState extends State<ScanScreen> {
  String _msg = 'Snap a receipt. Nothing counts until you confirm it.';
  bool _busy = false;

  Future<void> _snap() async {
    setState(() { _busy = true; _msg = 'Uploading…'; });
    try {
      final picked = await ImagePicker().pickImage(source: ImageSource.camera);
      final file = picked ?? await ImagePicker().pickImage(source: ImageSource.gallery);
      if (file == null) { setState(() { _msg = 'No receipt picked.'; _busy = false; }); return; }
      final bytes = await file.readAsBytes();
      final intake = await widget.api.uploadReceipt(bytes, file.name);
      setState(() => _msg = 'Receipt preserved. Reading it…');
      final extraction = await widget.api.extract(intake['evidence_id'] as String);
      widget.onExtracted(extraction);
    } catch (e) {
      setState(() => _msg = 'Could not read that receipt: $e');
    } finally {
      setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
          const Text('Snap a receipt', style: TextStyle(fontSize: 28, fontWeight: FontWeight.bold)),
          const SizedBox(height: 8),
          Text(_msg, textAlign: TextAlign.center),
          const SizedBox(height: 24),
          ElevatedButton.icon(
            onPressed: _busy ? null : _snap,
            icon: const Icon(Icons.camera_alt),
            label: const Text('Capture'),
          ),
        ]),
      ),
    );
  }
}

class ReviewScreen extends StatefulWidget {
  const ReviewScreen({super.key, required this.api, required this.extraction});
  final PiaApi api;
  final Map<String, dynamic>? extraction;
  @override
  State<ReviewScreen> createState() => _ReviewScreenState();
}

class _ReviewScreenState extends State<ReviewScreen> {
  String _msg = '';
  final Map<String, TextEditingController> _edits = {};
  final Map<String, String> _thumbs = {};

  @override
  void initState() {
    super.initState();
    _loadThumbs();
  }

  /// Product photo per receipt line, by the barcode in its raw text.
  /// No photo found = initial-letter placeholder, never a wrong picture.
  Future<void> _loadThumbs() async {
    final ext = widget.extraction;
    if (ext == null) return;
    for (final l in (ext['lines'] as List<dynamic>)) {
      final lineId = l['line_id'] as String;
      final raw = (l['raw_text'] as String?) ?? '';
      final upc = RegExp(r'\b\d{12,13}\b').firstMatch(raw)?.group(0);
      final url = await widget.api.productImage(
          upc: upc, name: l['normalized_name_candidate'] as String?);
      if (url != null && mounted) setState(() => _thumbs[lineId] = url);
    }
  }

  @override
  void dispose() {
    for (final c in _edits.values) { c.dispose(); }
    super.dispose();
  }

  Future<void> _confirm() async {
    final ext = widget.extraction;
    if (ext == null) return;
    setState(() => _msg = 'Confirming…');
    try {
      final lines = (ext['lines'] as List<dynamic>);
      final payload = {
        'evidence_id': ext['evidence_id'],
        'extraction_id': ext['extraction_id'],
        'merchant': ext['merchant_normalized_candidate'],
        'purchase_date': ext['purchase_date_candidate'],
        'purchase_time': ext['purchase_time_candidate'],
        'subtotal': ext['subtotal_candidate'],
        'tax': ext['tax_candidate'],
        'total': ext['total_candidate'],
        'items': lines.map((l) {
          final edited = _edits[l['line_id'] as String]?.text;
          return {
            'source_line_id': l['line_id'],
            'item_name': (edited != null && edited.isNotEmpty) ? edited : l['normalized_name_candidate'],
            'quantity': l['quantity_candidate'],
            'unit_price': l['unit_price_candidate'],
            'line_total': l['line_total_candidate'],
          };
        }).toList(),
      };
      final result = await widget.api.confirm(payload);
      setState(() => _msg = 'Confirmed. Purchase ${result['purchase_id']}. Pantry updated.');
    } catch (e) {
      setState(() => _msg = 'Confirm failed: $e');
    }
  }

  @override
  Widget build(BuildContext context) {
    final ext = widget.extraction;
    if (ext == null) {
      return const Center(child: Text('No receipt yet. Snap one on the Scan tab.'));
    }
    final lines = (ext['lines'] as List<dynamic>);
    return ListView(padding: const EdgeInsets.all(16), children: [
      Text('Review & Confirm — ${ext['merchant_normalized_candidate'] ?? ''}',
          style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
      const Text('Original receipt is kept separate. Nothing counts until you confirm.'),
      if (ext['suggestions'] != null && (ext['suggestions'] as Map).isNotEmpty)
        const Card(child: ListTile(title: Text('Suggestions from your corrections are flagged, never auto-applied.'))),
      ...lines.map((l) {
        final ctrl = _edits.putIfAbsent(
            l['line_id'] as String, () => TextEditingController(text: l['normalized_name_candidate'] ?? ''));
        final lineId = l['line_id'] as String;
        final thumbUrl = _thumbs[lineId];
        final itemName = l['normalized_name_candidate'] as String? ?? '';
        return Card(
          child: ListTile(
            leading: thumbUrl != null
                ? Image.network(thumbUrl, width: 56, height: 56, fit: BoxFit.contain,
                    errorBuilder: (_, _, _) => CircleAvatar(child: Text(itemName.isEmpty ? '?' : itemName[0])))
                : CircleAvatar(child: Text(itemName.isEmpty ? '?' : itemName[0])),
            title: TextField(controller: ctrl, decoration: const InputDecoration(labelText: 'Item name')),
            subtitle: Text('${l['raw_text'] ?? ''}'),
            trailing: Text('${l['line_total_candidate'] ?? ''}'),
          ),
        );
      }),
      const SizedBox(height: 12),
      ElevatedButton(onPressed: _confirm, child: const Text('Confirm purchase')),
      if (_msg.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 12), child: Text(_msg)),
    ]);
  }
}

class PantryScreen extends StatefulWidget {
  const PantryScreen({super.key, required this.api});
  final PiaApi api;
  @override
  State<PantryScreen> createState() => _PantryScreenState();
}

/// Pantry dashboard, like Tee's screenshot: search box on top with
/// "X of Y left", items grouped by purchase day
/// ("Wednesday afternoon, Nov 4 · 9 items"), one card per item with
/// its photo on top and its name below. Tap a card to mark it
/// In stock / Used / Gone. No photo found = plain initial placeholder.
class _PantryScreenState extends State<PantryScreen> {
  List<dynamic> _items = [];
  String _msg = '';
  String _query = '';
  final Map<String, String> _images = {};
  String? _openId;

  static const _weekdays = [
    'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'
  ];
  static const _months = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'
  ];

  @override
  void initState() { super.initState(); _load(); }

  Future<void> _load() async {
    try {
      final items = await widget.api.pantry();
      if (!mounted) return;
      setState(() => _items = items);
      for (final item in items) {
        final id = item['pantry_item_id'] as String;
        if (_images.containsKey(id)) continue;
        final url = await widget.api.productImage(name: item['item_name'] as String?);
        if (url != null && mounted) setState(() => _images[id] = url);
      }
    } catch (e) { if (mounted) setState(() => _msg = '$e'); }
  }

  Future<void> _set(String id, String status) async {
    await widget.api.pantryStatus(id, status);
    await _load();
  }

  String _partOfDay(DateTime d) {
    if (d.hour >= 5 && d.hour < 12) return 'morning';
    if (d.hour >= 12 && d.hour < 17) return 'afternoon';
    return 'night';
  }

  String _groupLabel(String iso) {
    final d = DateTime.tryParse(iso);
    if (d == null) return 'Undated';
    return '${_weekdays[d.weekday - 1]} ${_partOfDay(d)}, ${_months[d.month - 1]} ${d.day}';
  }

  @override
  Widget build(BuildContext context) {
    final query = _query.toLowerCase();
    final visible = _items.where((it) =>
        query.isEmpty || (it['item_name'] as String).toLowerCase().contains(query)).toList();
    final leftAll = _items.where((it) => it['status'] == 'in_stock').length;
    final leftVisible = visible.where((it) => it['status'] == 'in_stock').length;
    final groups = <String, List<dynamic>>{};
    for (final it in visible) {
      final key = ((it['created_at'] as String?) ?? '').split('T').first;
      groups.putIfAbsent(key, () => []).add(it);
    }
    final keys = groups.keys.toList()..sort((a, b) => b.compareTo(a));
    return ListView(padding: const EdgeInsets.all(16), children: [
      Row(children: [
        Expanded(
          child: TextField(
            decoration: const InputDecoration(
              hintText: 'Find something...',
              border: OutlineInputBorder(),
              filled: true,
              fillColor: Colors.white,
            ),
            onChanged: (v) => setState(() => _query = v),
          ),
        ),
        const SizedBox(width: 12),
        Text('$leftVisible of $leftAll left', style: const TextStyle(fontWeight: FontWeight.bold)),
      ]),
      const SizedBox(height: 8),
      const Text('Tap a card to mark it In stock, Used, or Gone.'),
      for (final key in keys) ...[
        const SizedBox(height: 20),
        Text(
          '${_groupLabel((groups[key]!.first['created_at'] as String?) ?? '')} · ${groups[key]!.length} item${groups[key]!.length == 1 ? '' : 's'}',
          style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
        ),
        const SizedBox(height: 8),
        GridView.builder(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: 3,
            crossAxisSpacing: 10,
            mainAxisSpacing: 10,
            childAspectRatio: 0.72,
          ),
          itemCount: groups[key]!.length,
          itemBuilder: (context, i) {
            final item = groups[key]![i];
            final id = item['pantry_item_id'] as String;
            final name = item['item_name'] as String;
            final qty = (item['qty_on_hand'] as num?)?.toDouble() ?? 1;
            final imageUrl = _images[id];
            final open = _openId == id;
            return GestureDetector(
              onTap: () => setState(() => _openId = open ? null : id),
              child: Card(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Expanded(
                    child: Stack(children: [
                      Container(
                        width: double.infinity,
                        color: Colors.white,
                        alignment: Alignment.center,
                        child: imageUrl != null
                            ? Image.network(imageUrl, fit: BoxFit.contain,
                                errorBuilder: (_, _, _) => Text(name.isEmpty ? '?' : name[0],
                                    style: const TextStyle(fontSize: 40, fontWeight: FontWeight.bold)))
                            : Text(name.isEmpty ? '?' : name[0],
                                style: const TextStyle(fontSize: 40, fontWeight: FontWeight.bold)),
                      ),
                      if (qty > 1)
                        Positioned(
                          top: 6, right: 6,
                          child: CircleAvatar(radius: 13, backgroundColor: Colors.red,
                              child: Text('×${qty.toInt()}', style: const TextStyle(fontSize: 12, color: Colors.white))),
                        ),
                    ]),
                  ),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(10, 8, 10, 2),
                    child: Text(name, style: const TextStyle(fontWeight: FontWeight.bold), maxLines: 2, overflow: TextOverflow.ellipsis),
                  ),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(10, 0, 10, 8),
                    child: Text(
                      "${item['status']}${item['low'] == true ? ' · Low' : ''} · qty ${qty.toStringAsFixed(qty.truncateToDouble() == qty ? 0 : 1)}",
                      style: const TextStyle(fontSize: 12, color: Colors.black54),
                    ),
                  ),
                  if (open)
                    Padding(
                      padding: const EdgeInsets.fromLTRB(8, 0, 8, 8),
                      child: Wrap(spacing: 6, children: [
                        TextButton(onPressed: () => _set(id, 'in_stock'), child: const Text('In stock')),
                        TextButton(onPressed: () => _set(id, 'used'), child: const Text('Used')),
                        TextButton(onPressed: () => _set(id, 'gone'), child: const Text('Gone')),
                      ]),
                    ),
                ]),
              ),
            );
          },
        ),
      ],
      const SizedBox(height: 16),
      ElevatedButton.icon(
        onPressed: () async {
          final name = TextEditingController();
          final qty = TextEditingController(text: '1');
          final ok = await showDialog<bool>(
            context: context,
            builder: (c) => AlertDialog(
              title: const Text('Add item'),
              content: Column(mainAxisSize: MainAxisSize.min, children: [
                TextField(controller: name, decoration: const InputDecoration(labelText: 'Item name')),
                TextField(controller: qty, decoration: const InputDecoration(labelText: 'Quantity')),
              ]),
              actions: [
                TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
                TextButton(onPressed: () => Navigator.pop(c, true), child: const Text('Add')),
              ],
            ),
          );
          if (ok == true && name.text.isNotEmpty) {
            await widget.api.addPantryItem(name.text, qty.text);
            await _load();
          }
        },
        icon: const Icon(Icons.add),
        label: const Text('Add item'),
      ),
      if (_msg.isNotEmpty) Text(_msg),
    ]);
  }
}

class AnalyticsScreen extends StatefulWidget {
  const AnalyticsScreen({super.key, required this.api});
  final PiaApi api;
  @override
  State<AnalyticsScreen> createState() => _AnalyticsScreenState();
}

class _AnalyticsScreenState extends State<AnalyticsScreen> {
  Map<String, dynamic>? _weekly;
  Map<String, dynamic>? _most;

  @override
  void initState() { super.initState(); _load(); }

  Future<void> _load() async {
    try {
      final w = await widget.api.weekly();
      final m = await widget.api.mostBought();
      setState(() { _weekly = w; _most = m; });
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    final weekly = (_weekly?['weekly_spending'] as Map?) ?? {};
    final most = (_most?['most_bought'] as List?) ?? [];
    return ListView(padding: const EdgeInsets.all(16), children: [
      const Text('Purchase memory & analytics', style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
      const Text('Confirmed purchases only. Unconfirmed extractions never count.'),
      const SizedBox(height: 12),
      const Text('Weekly spending', style: TextStyle(fontWeight: FontWeight.bold)),
      ...weekly.entries.map((e) => ListTile(title: Text(e.key), trailing: Text('\$${e.value}'))),
      const SizedBox(height: 12),
      const Text('Most-bought items', style: TextStyle(fontWeight: FontWeight.bold)),
      ...most.map((item) => ListTile(
            title: Text('${item['item_name']}'),
            trailing: Text('${item['occurrence_count']} purchases'),
          )),
    ]);
  }
}
