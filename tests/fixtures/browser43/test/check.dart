import 'package:collection/collection.dart';
void main() {
  if ([1, 2, 3].sum != 6) throw StateError('locked dependency failed');
}
