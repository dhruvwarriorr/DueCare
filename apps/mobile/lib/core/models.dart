// Typed views over the API's JSON (apps/web/src/lib/types.ts). Each is the response map itself,
// so cached JSON can be shown before the network answers without any conversion step.

typedef Json = Map<String, dynamic>;

List<T> _list<T>(Object? value) => value is List ? value.cast<T>() : <T>[];
Json? _map(Object? value) => value is Map ? value.cast<String, dynamic>() : null;

extension type Profile(Json json) {
  String get id => json['id'] as String;
  int get revision => json['revision'] as int;
  Json get identity => _map(json['identity']) ?? {};
  String? get name => identity['name'] as String?;
  String get email => (identity['email'] as String?) ?? '';
  bool get onboardingComplete => json['onboardingComplete'] == true;
  String get theme => (json['theme'] as String?) ?? 'system';
  bool get ignoreKtNotices => json['ignoreKtNotices'] == true;
  String? get branchCode => json['branchCode'] as String?;
  String? get classYear => json['classYear'] as String?;
  int? get currentSemester => (json['currentSemester'] as num?)?.toInt();
  String? get division => json['division'] as String?;
  String? get generalBatch => json['generalBatch'] as String?;
  String? get rollNumber => json['rollNumber'] as String?;
  List<({String code, String name})> get branchOptions => _list<Map>(json['branchOptions'])
      .map((b) => (code: b['code'] as String, name: b['name'] as String))
      .toList();

  /// "SY · COMPS · Div A · Batch A1"
  String get academicLine => [
        classYear,
        branchCode,
        if (division != null && division!.isNotEmpty) 'Div $division',
        if (generalBatch != null && generalBatch!.isNotEmpty) 'Batch $generalBatch',
      ].whereType<String>().where((s) => s.isNotEmpty).join(' · ');

  String get initial => (name?.isNotEmpty ?? false) ? name!.substring(0, 1) : 'S';
}

extension type Subject(Json json) {
  String get id => json['id'] as String;
  int get revision => json['revision'] as int;
  String get name => json['name'] as String;
  String get kind => json['kind'] as String;
  String? get code => json['code'] as String?;
  String? get term => json['term'] as String?;
  String? get classCode => json['classCode'] as String?;
  List<String> get aliases => _list<String>(json['aliases']);
  List<Json> get classroomMappings => _list<Map>(json['classroomMappings']).map((m) => m.cast<String, dynamic>()).toList();
  String get label => '$name · $kind';
}

extension type Task(Json json) {
  String get id => json['id'] as String;
  int get revision => json['revision'] as int;
  String get title => json['title'] as String;
  String? get sourceTitle => json['sourceTitle'] as String?;
  String get type => json['type'] as String;
  bool get isTest => type == 'test';
  String get status => json['status'] as String;
  String? get subjectId => json['subjectId'] as String?;
  String? get subjectName => json['subjectName'] as String?;
  String? get subjectKind => json['subjectKind'] as String?;
  String? get generalBatch => json['generalBatch'] as String?;
  String get priority => (json['priority'] as String?) ?? 'low';
  String? get priorityOverride => json['priorityOverride'] as String?;
  String? get dueAt => json['dueAt'] as String?;
  String? get dueDate => json['dueDate'] as String?;
  String get instructions => (json['instructions'] as String?) ?? '';
  String get notes => (json['notes'] as String?) ?? '';
  String? get dateWindowStart => json['dateWindowStart'] as String?;
  String? get dateWindowEnd => json['dateWindowEnd'] as String?;
  String? get completedAt => json['completedAt'] as String?;
  String? get completionOrigin => json['completionOrigin'] as String?;
  String get createdAt => json['createdAt'] as String;
  String get source => (json['source'] as String?) ?? 'manual';
  List<String> get sources => _list<String>(json['sources']);
  Json get timingProvenance => _map(json['timingProvenance']) ?? {};
  Json? get timingTentative => _map(json['timingTentative']);
  Json? get hiddenByRule => _map(json['hiddenByRule']);
  Json? get classroom => _map(json['classroom']);
  Json? get subjectLink => _map(json['subjectLink']);
  List<String> get senderEmails => _list<String>(json['senderEmails']);
  Object? operator [](String key) => json[key];

  String? basisOf(String field) => _map(timingProvenance[field])?['basis'] as String?;
}

extension type Slot(Json json) {
  String? get id => json['id'] as String?;
  int get weekday => (json['weekday'] as num).toInt();
  String get startTime => (json['startTime'] as String?) ?? '';
  String get endTime => (json['endTime'] as String?) ?? '';
  String? get location => json['location'] as String?;
  String? get validFrom => json['validFrom'] as String?;
  String? get validUntil => json['validUntil'] as String?;
}

extension type HistoryItem(Json json) {
  String get action => json['action'] as String;
  String get actor => (json['actor'] as String?) ?? 'student';
  Json get changes => _map(json['changes']) ?? {};
  String get recordedAt => json['recordedAt'] as String;
}

extension type Connection(Json json) {
  String get id => json['id'] as String;
  String get service => json['service'] as String;
  String get status => json['status'] as String;
  int get revision => json['revision'] as int;
  String? get privacyJobId => json['privacyJobId'] as String?;
  String get accountEmail => (_map(json['account'])?['email'] as String?) ?? '';
  List<String> get permissions => _list<String>(json['permissions']);
  List<String> get optionalPermissionsMissing => _list<String>(json['optionalPermissionsMissing']);
  String? get lastSuccessAt => json['lastSuccessAt'] as String?;
  Json? get lastError => _map(json['lastError']);
  Json? get activeJob => _map(json['activeJob']);
  Json? get lastJob => _map(json['lastJob']);
  Json get records => _map(json['records']) ?? {};
  String get label => service == 'gmail' ? 'Gmail' : 'Google Classroom';
}

extension type ReviewItem(Json json) {
  String get id => json['id'] as String;
  int get revision => json['revision'] as int;
  String get issueType => json['issueType'] as String;
  String get question => (json['question'] as String?) ?? '';
  String? get taskId => json['taskId'] as String?;
  String? get taskTitle => json['taskTitle'] as String?;
  String? get senderEmail => json['senderEmail'] as String?;
  Json? get observed => _map(json['observed']);
  Json? get student => _map(json['student']);
  Json get proposal => _map(json['proposal']) ?? {};
  Json? get conflicts => _map(json['conflicts']);
  List<String>? get window => json['window'] == null ? null : _list<String>(json['window']);
  List<String> get alternatives => _list<String>(json['alternatives']);
  List<String> get subjectChoices => _list<String>(json['subjectChoices']);
  String? get courseLabel => json['courseLabel'] as String?;
  String? get excerpt => json['excerpt'] as String?;
  String? get sourceTitle => json['sourceTitle'] as String?;
  String? get sourceKind => json['sourceKind'] as String?;
  int get evidenceCount => (json['evidenceCount'] as num?)?.toInt() ?? 0;
  String get createdAt => json['createdAt'] as String;
}

extension type Rule(Json json) {
  String get id => json['id'] as String;
  int get revision => json['revision'] as int;
  String get name => (json['name'] as String?) ?? '';
  bool get enabled => json['enabled'] == true;
  int get affects => (json['affects'] as num?)?.toInt() ?? 0;
  List<Json> get conditions => _list<Map>(json['conditions']).map((c) => c.cast<String, dynamic>()).toList();
  Json get action => _map(json['action']) ?? {};
}

extension type Evidence(Json json) {
  String get id => json['id'] as String;
  String get eventType => (json['eventType'] as String?) ?? '';
  String get state => (json['state'] as String?) ?? 'active';
  String get sourceKind => (json['sourceKind'] as String?) ?? '';
  String? get sender => json['sender'] as String?;
  String? get senderName => json['senderName'] as String?;
  String? get postedAt => json['postedAt'] as String?;
  String? get courseName => json['courseName'] as String?;
  String? get postedBy => json['postedBy'] as String?;
  String? get openUrl => json['openUrl'] as String?;
  String? get sourceTitle => json['sourceTitle'] as String?;
  String? get excerpt => json['excerpt'] as String?;
}

extension type ActivityItem(Json json) {
  String get id => json['id'] as String;
  int get revision => json['revision'] as int;
  String get message => (json['message'] as String?) ?? '';
  String get targetType => (json['targetType'] as String?) ?? '';
  String get targetId => (json['targetId'] as String?) ?? '';
  String? get readAt => json['readAt'] as String?;
  String get createdAt => json['createdAt'] as String;
}

extension type PrivacyJob(Json json) {
  String get id => json['id'] as String;
  String get kind => (json['kind'] as String?) ?? '';
  String get status => (json['status'] as String?) ?? '';
  String get stage => (json['stage'] as String?) ?? '';
  Json get progress => _map(json['progress']) ?? {};
  String? get errorCode => json['errorCode'] as String?;
}

/// A page of a cursor-paginated list.
({List<Json> items, String? nextCursor}) pageOf(Object? data) {
  final m = _map(data) ?? {};
  return (
    items: _list<Map>(m['items']).map((i) => i.cast<String, dynamic>()).toList(),
    nextCursor: m['nextCursor'] as String?,
  );
}
