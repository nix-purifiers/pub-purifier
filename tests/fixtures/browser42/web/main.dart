import 'dart:js_interop';
import 'values.dart' deferred as values;
@JS('purifierSetAnswer')
external void setAnswer(JSNumber value);
Future<void> main() async { await values.loadLibrary(); setAnswer(values.answer().toJS); }
